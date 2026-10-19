package main

import (
	"archive/tar"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"log"
	"math/big"
	"net"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

type Transfer struct {
	ID, Nonce, Code, Digest, Peer, Name, Version, AppID, Directory, Phase string
	Created                                                               time.Time
	ViaTailnet                                                            bool
}

var appIDPattern = regexp.MustCompile("^[a-z0-9_-][a-z0-9._-]{0,62}$")
var noncePattern = regexp.MustCompile("^[0-9a-f]{32}$")

func randomID() string {
	b := make([]byte, 16)
	if _, e := rand.Read(b); e != nil {
		panic(e)
	}
	return hex.EncodeToString(b)
}
func confirmationCode(certificate []byte, digest, nonce string) string {
	h := sha256.New()
	h.Write(certificate)
	h.Write([]byte{0})
	h.Write([]byte(digest))
	h.Write([]byte{0})
	h.Write([]byte(nonce))
	sum := h.Sum(nil)
	n := (uint32(sum[0])<<24 | uint32(sum[1])<<16 | uint32(sum[2])<<8 | uint32(sum[3])) % 1000000
	return fmt.Sprintf("%06d", n)
}
func (s *Service) ensureCertificate() (tls.Certificate, error) {
	certPath, keyPath := filepath.Join(s.root, "receiver-cert.pem"), filepath.Join(s.root, "receiver-key.pem")
	if _, e := os.Stat(certPath); os.IsNotExist(e) {
		key, e := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
		if e != nil {
			return tls.Certificate{}, e
		}
		serial, e := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
		if e != nil {
			return tls.Certificate{}, e
		}
		cert := &x509.Certificate{SerialNumber: serial, Subject: pkix.Name{CommonName: "PaperOS local application receiver"},
			NotBefore: time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC), NotAfter: time.Date(2040, 1, 1, 0, 0, 0, 0, time.UTC),
			KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
			BasicConstraintsValid: true, IsCA: true, DNSNames: []string{"paperos.local"}, IPAddresses: []net.IP{net.ParseIP("127.0.0.1")}}
		der, e := x509.CreateCertificate(rand.Reader, cert, cert, &key.PublicKey, key)
		if e != nil {
			return tls.Certificate{}, e
		}
		raw, e := x509.MarshalPKCS8PrivateKey(key)
		if e != nil {
			return tls.Certificate{}, e
		}
		if e = atomicWrite(keyPath, pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: raw}), 0600); e != nil {
			return tls.Certificate{}, e
		}
		if e = atomicWrite(certPath, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}), 0644); e != nil {
			return tls.Certificate{}, e
		}
	}
	pair, e := tls.LoadX509KeyPair(certPath, keyPath)
	if e == nil {
		s.certificate = pair.Certificate[0]
	}
	return pair, e
}
func (s *Service) reconcileReceiver() {
	s.mu.Lock()
	defer s.mu.Unlock()
	on := s.receiveUntil.After(time.Now()) && s.cfg.WiFi && !s.cfg.Airplane && s.net.Connected
	remote := on && s.cfg.Tailnet.AllowReceive && s.tailnetConnectedLocked()
	if !on || (s.receiver != nil && s.receiverIP != s.net.IP) {
		if s.receiver != nil {
			_ = s.receiver.Close()
			s.receiver = nil
			s.receiverIP = ""
		}
	}
	if !remote {
		if s.receiverTailnet != nil {
			_ = s.receiverTailnet.Close()
			s.receiverTailnet = nil
		}
		s.rejectTailnetPendingLocked()
	}
	if !on {
		if s.pending != nil && time.Since(s.pending.Created) > 10*time.Minute {
			p := s.pending
			s.pending = nil
			p.Phase = "expired"
			go os.RemoveAll(p.Directory)
		}
		return
	}
	if s.receiver != nil && (!remote || s.receiverTailnet != nil) {
		return
	}
	pair, e := s.ensureCertificate()
	if e != nil {
		s.message = "无法建立加密接收服务"
		return
	}
	if s.receiver == nil {
		server, e := s.newReceiver(net.JoinHostPort(s.net.IP, "8765"), pair, false)
		if e != nil {
			s.message = "应用接收端口不可用"
		} else {
			s.receiver = server
			s.receiverIP = s.net.IP
		}
	}
	if remote && s.receiverTailnet == nil {
		// Tailscale userspace networking forwards inbound TCP to localhost.
		// Keep the LAN listener on its specific Wi-Fi address; never bind *.
		if s.net.IP == "127.0.0.1" {
			s.message = "模拟无线地址与远程接收冲突"
			return
		}
		server, e := s.newReceiver("127.0.0.1:8765", pair, true)
		if e != nil {
			s.message = "远程接收端口不可用"
		} else {
			s.receiverTailnet = server
		}
	}
}

type tailnetReceiverContext struct{}

func (s *Service) newReceiver(address string, pair tls.Certificate, remote bool) (*http.Server, error) {
	listener, e := tls.Listen("tcp", address, &tls.Config{Certificates: []tls.Certificate{pair}, MinVersion: tls.VersionTLS12})
	if e != nil {
		return nil, e
	}
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if remote {
			r = r.WithContext(context.WithValue(r.Context(), tailnetReceiverContext{}, true))
		}
		s.transferHandler(w, r)
	})
	// net/http starts WriteTimeout after reading the headers, before reading
	// the upload body. Reserve the entire read budget plus response time.
	server := &http.Server{Handler: handler, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 90 * time.Second, WriteTimeout: 2 * time.Minute, MaxHeaderBytes: 8192}
	go func() { _ = server.Serve(listener) }()
	return server, nil
}

func (s *Service) rejectTailnetPendingLocked() {
	if p := s.pending; p != nil && p.ViaTailnet {
		p.Phase = "rejected"
		s.pending = nil
		go os.RemoveAll(p.Directory)
	}
}

func (s *Service) transferAllowedLocked(remote bool) bool {
	on := s.receiveUntil.After(time.Now()) && !s.cfg.Airplane && s.net.Connected
	return on && (!remote || (s.cfg.WiFi && s.cfg.Tailnet.AllowReceive && s.tailnetConnectedLocked()))
}
func unpackPackage(reader io.Reader, directory string) (map[string]string, error) {
	tr := tar.NewReader(reader)
	total := int64(0)
	count := 0
	seen := map[string]bool{}
	for {
		header, e := tr.Next()
		if errors.Is(e, io.EOF) {
			break
		}
		if e != nil {
			return nil, e
		}
		name := header.Name
		if strings.ContainsAny(name, "\\\x00\r\n\t") || strings.HasPrefix(name, "/") || path.Clean(name) != strings.TrimSuffix(name, "/") {
			return nil, errors.New("unsafe package path")
		}
		parts := strings.Split(strings.TrimSuffix(name, "/"), "/")
		if len(parts) < 2 || parts[0] != "package" || len(parts) > 10 {
			return nil, errors.New("invalid package nesting")
		}
		for _, part := range parts {
			if part == "" || part == "." || part == ".." {
				return nil, errors.New("invalid path component")
			}
		}
		if seen[name] {
			return nil, errors.New("duplicate package entry")
		}
		seen[name] = true
		count++
		if count > 256 {
			return nil, errors.New("too many package files")
		}
		target := filepath.Join(directory, filepath.FromSlash(name))
		if header.Typeflag == tar.TypeDir {
			if e = os.MkdirAll(target, 0755); e != nil {
				return nil, e
			}
			continue
		}
		if header.Typeflag != tar.TypeReg || header.Size < 0 {
			return nil, errors.New("links and special files are not allowed")
		}
		total += header.Size
		if total > 64*1024*1024 {
			return nil, errors.New("package exceeds 64MiB")
		}
		if e = os.MkdirAll(filepath.Dir(target), 0755); e != nil {
			return nil, e
		}
		mode := os.FileMode(0644)
		if header.Mode&0111 != 0 {
			mode = 0755
		}
		f, e := os.OpenFile(target, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
		if e != nil {
			return nil, e
		}
		n, e := io.CopyN(f, tr, header.Size)
		closeErr := f.Close()
		if e != nil || n != header.Size || closeErr != nil {
			return nil, errors.New("incomplete package entry")
		}
	}
	return readAppManifest(filepath.Join(directory, "package"))
}

func readAppManifest(directory string) (map[string]string, error) {
	data, e := os.ReadFile(filepath.Join(directory, "manifest.conf"))
	if e != nil || len(data) == 0 || len(data) > 8192 || !utf8.Valid(data) {
		return nil, errors.New("invalid manifest")
	}
	manifest := map[string]string{}
	allowed := map[string]bool{"id": true, "name": true, "version": true, "exec": true, "description": true, "widget": true}
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSuffix(line, "\r")
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok || !allowed[key] || value == "" || strings.IndexFunc(value, func(r rune) bool { return r < 32 || r == 127 }) >= 0 {
			return nil, errors.New("invalid manifest field")
		}
		if _, ok = manifest[key]; ok {
			return nil, errors.New("duplicate manifest field")
		}
		manifest[key] = value
	}
	for _, key := range []string{"id", "name", "version", "exec"} {
		if manifest[key] == "" {
			return nil, errors.New("missing manifest field")
		}
	}
	if !appIDPattern.MatchString(manifest["id"]) || strings.Contains(manifest["id"], "..") || len(manifest["name"]) >= 128 || len(manifest["version"]) >= 32 || len(manifest["description"]) >= 256 {
		return nil, errors.New("invalid application metadata")
	}
	program := manifest["exec"]
	if path.IsAbs(program) || path.Clean(program) != program || strings.HasPrefix(program, "../") || len(program) >= 160 {
		return nil, errors.New("invalid application entry point")
	}
	if info, e := os.Stat(filepath.Join(directory, filepath.FromSlash(program))); e != nil || !info.Mode().IsRegular() {
		return nil, errors.New("missing application entry point")
	}
	if w := manifest["widget"]; w != "" && w != "clock" && w != "calendar" && w != "weather" && w != "mihome" {
		return nil, errors.New("unsupported widget type")
	}
	return manifest, nil
}
func jsonReply(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func (s *Service) transferHandler(w http.ResponseWriter, r *http.Request) {
	if r.Header.Get("Origin") != "" {
		http.Error(w, "browser origins are not accepted", 403)
		return
	}
	remote, _ := r.Context().Value(tailnetReceiverContext{}).(bool)
	s.mu.Lock()
	enabled := s.transferAllowedLocked(remote)
	s.mu.Unlock()
	if !enabled {
		http.Error(w, "receiver disabled", 403)
		return
	}
	if r.Method == "GET" && r.URL.Path == "/status" {
		s.mu.Lock()
		defer s.mu.Unlock()
		p := s.transfers[r.URL.Query().Get("id")]
		if p == nil || p.Nonce != r.URL.Query().Get("nonce") {
			http.Error(w, "unknown request", 404)
			return
		}
		jsonReply(w, 200, map[string]string{"status": p.Phase})
		return
	}
	if r.Method != "POST" || r.URL.Path != "/upload" {
		http.Error(w, "not found", 404)
		return
	}
	nonce, digest := r.Header.Get("X-PaperOS-Nonce"), r.Header.Get("X-PaperOS-SHA256")
	raw, e := hex.DecodeString(digest)
	if !noncePattern.MatchString(nonce) || e != nil || len(raw) != sha256.Size || r.ContentLength <= 0 || r.ContentLength > 66*1024*1024 {
		http.Error(w, "invalid upload metadata", 400)
		return
	}
	s.mu.Lock()
	if s.pending != nil || s.uploading {
		s.mu.Unlock()
		http.Error(w, "another request is pending", 409)
		return
	}
	// Incomplete packages are never shown for approval.
	p := &Transfer{ID: randomID(), Nonce: nonce, Digest: digest, Phase: "receiving", Created: time.Now(), ViaTailnet: remote}
	s.uploading = true
	s.mu.Unlock()
	success := false
	defer func() {
		s.mu.Lock()
		s.uploading = false
		s.mu.Unlock()
		if !success && p.Directory != "" {
			_ = os.RemoveAll(p.Directory)
		}
	}()
	if e = os.MkdirAll(s.packages, 0755); e != nil {
		http.Error(w, "package store unavailable", 503)
		return
	}
	p.Directory, e = os.MkdirTemp(s.packages, ".receiving-")
	if e != nil {
		http.Error(w, "no staging space", 503)
		return
	}
	filePath := filepath.Join(p.Directory, "upload.tar")
	file, e := os.OpenFile(filePath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if e != nil {
		http.Error(w, "staging unavailable", 503)
		return
	}
	hash := sha256.New()
	n, e := io.Copy(io.MultiWriter(file, hash), http.MaxBytesReader(w, r.Body, 66*1024*1024))
	closeErr := file.Close()
	if e != nil || closeErr != nil || n != r.ContentLength || hex.EncodeToString(hash.Sum(nil)) != digest {
		log.Printf("Application upload incomplete from %s: %d/%d bytes after %s; read=%v close=%v", r.RemoteAddr, n, r.ContentLength, time.Since(p.Created).Round(time.Millisecond), e, closeErr)
		http.Error(w, "upload checksum mismatch", 400)
		return
	}
	in, e := os.Open(filePath)
	if e != nil {
		http.Error(w, "staging read failed", 503)
		return
	}
	manifest, e := unpackPackage(in, p.Directory)
	in.Close()
	if e != nil {
		http.Error(w, "invalid application package", 400)
		return
	}
	_ = os.Remove(filePath)
	peer, _, _ := net.SplitHostPort(r.RemoteAddr)
	s.mu.Lock()
	if s.pending != nil || !s.transferAllowedLocked(remote) {
		s.mu.Unlock()
		http.Error(w, "request expired", 409)
		return
	}
	p.Name = manifest["name"]
	p.Version = manifest["version"]
	p.AppID = manifest["id"]
	p.Peer = peer
	if remote {
		p.Peer = "Tailscale 私网"
	}
	p.Code = confirmationCode(s.certificate, digest, nonce)
	p.Phase = "pending"
	s.pending = p
	// Keep recent status objects bounded; unapproved requests never execute code.
	if len(s.transfers) > 32 {
		for id, t := range s.transfers {
			if time.Since(t.Created) > 10*time.Minute {
				delete(s.transfers, id)
			}
		}
	}
	s.transfers[p.ID] = p
	s.mu.Unlock()
	success = true
	s.publish()
	jsonReply(w, 202, map[string]string{"id": p.ID, "status": "pending"})
}
func (s *Service) acceptTransfer(p *Transfer) {
	destination := filepath.Join(s.packages, p.AppID+".papp")
	previous := filepath.Join(s.packages, ".previous-"+p.ID)
	source := filepath.Join(p.Directory, "package")
	existed := false
	if _, e := os.Lstat(destination); e == nil {
		if e = os.Rename(destination, previous); e != nil {
			s.finishTransfer(p, "failed", "应用库忙碌，接收失败")
			return
		}
		existed = true
	}
	if e := os.Rename(source, destination); e != nil {
		if existed {
			_ = os.Rename(previous, destination)
		}
		s.finishTransfer(p, "failed", "保存应用包失败")
		return
	}
	if existed {
		_ = os.RemoveAll(previous)
	}
	_ = os.RemoveAll(p.Directory)
	s.finishTransfer(p, "received", "应用包已接收，请到应用库安装")
}
func (s *Service) finishTransfer(p *Transfer, phase, message string) {
	s.mu.Lock()
	p.Phase = phase
	s.message = message
	s.mu.Unlock()
	s.publish()
}

// Used by the sender and tests to show a short human-verifiable TLS/package binding.
func shortCertificate(certificate []byte) string {
	sum := sha256.Sum256(certificate)
	return strconv.FormatUint(uint64(sum[0])<<24|uint64(sum[1])<<16|uint64(sum[2])<<8|uint64(sum[3]), 16)
}
