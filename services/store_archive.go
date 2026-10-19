package main

import (
	"archive/tar"
	"archive/zip"
	"bufio"
	"compress/gzip"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"github.com/klauspost/compress/zstd"
)

const storeMaxArchive int64 = 64 << 20
const storeMaxExpanded int64 = 128 << 20
const storeMaxFiles = 4096

// Extraction never follows links, preserves special permissions, or runs hooks.
// Work directories are fresh, private to this download, and remain noexec.
type storeExtractor struct {
	root  string
	seen  map[string]bool
	paths map[string]string
	count int
	total int64
}

func (x *storeExtractor) add(name string, mode os.FileMode, size int64, reader io.Reader, directory bool) error {
	name = strings.TrimSuffix(name, "/")
	if name == "." && directory {
		return nil
	}
	if strings.HasPrefix(name, "./") {
		name = strings.TrimPrefix(name, "./")
	}
	if name == "" || !utf8.ValidString(name) || path.IsAbs(name) || path.Clean(name) != name || strings.ContainsAny(name, "\\\x00\r\n\t:") || len(name) > 640 || len(strings.Split(name, "/")) > 16 {
		return errors.New("安装包包含不安全路径")
	}
	for _, part := range strings.Split(name, "/") {
		if part == ".." || part == "." || part == "" {
			return errors.New("安装包路径无效")
		}
	}
	key := strings.ToLower(name)
	if x.paths == nil {
		x.paths = map[string]string{}
	}
	parts := strings.Split(name, "/")
	for i := range parts {
		prefix := strings.Join(parts[:i+1], "/")
		folded := strings.ToLower(prefix)
		if old, ok := x.paths[folded]; ok && old != prefix {
			return errors.New("安装包目录存在大小写冲突")
		}
		x.paths[folded] = prefix
	}
	if x.seen[key] {
		return errors.New("安装包包含重复或大小写冲突的文件")
	}
	x.seen[key] = true
	x.count++
	if x.count > storeMaxFiles || size < 0 || size > storeMaxExpanded || x.total > storeMaxExpanded-size {
		return errors.New("安装包展开后过大")
	}
	target := filepath.Join(x.root, filepath.FromSlash(name))
	if directory {
		return os.MkdirAll(target, 0700)
	}
	if !mode.IsRegular() {
		return errors.New("安装包包含链接或特殊文件")
	}
	x.total += size
	if err := storeFreeSpace(x.root, size+(4<<20)); err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(target), 0700); err != nil {
		return err
	}
	permissions := os.FileMode(0600)
	if mode&0111 != 0 {
		permissions = 0700
	}
	file, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, permissions)
	if err != nil {
		return err
	}
	n, err := io.CopyN(file, reader, size)
	closeErr := file.Close()
	if err != nil || n != size {
		return errors.New("安装包文件不完整")
	}
	return closeErr
}
func unpackStoreArchive(archive, directory string) error {
	info, err := os.Stat(archive)
	if err != nil {
		return err
	}
	if info.Size() > storeMaxArchive {
		return errors.New("下载文件超过 64 MiB")
	}
	x := storeExtractor{root: directory, seen: map[string]bool{}}
	if err = os.MkdirAll(directory, 0700); err != nil {
		return err
	}
	file, err := os.Open(archive)
	if err != nil {
		return err
	}
	defer file.Close()
	magic := make([]byte, 6)
	n, _ := file.Read(magic)
	magic = magic[:n]
	_, _ = file.Seek(0, 0)
	if len(magic) >= 4 && string(magic[:2]) == "PK" {
		zr, err := zip.NewReader(file, info.Size())
		if err != nil {
			return err
		}
		for _, entry := range zr.File {
			if entry.UncompressedSize64 > uint64(storeMaxExpanded) {
				return errors.New("ZIP 文件展开后过大")
			}
			rc, err := entry.Open()
			if err != nil {
				return err
			}
			err = x.add(entry.Name, entry.Mode(), int64(entry.UncompressedSize64), rc, entry.FileInfo().IsDir())
			if err == nil {
				// ZIP verifies CRC at EOF, which CopyN alone need not reach.
				var tail [1]byte
				n, endErr := rc.Read(tail[:])
				if n != 0 || endErr != io.EOF {
					err = errors.New("ZIP 校验失败或文件长度不符")
				}
			}
			closeErr := rc.Close()
			if err != nil {
				return err
			}
			if closeErr != nil {
				return closeErr
			}
		}
		return nil
	}
	var reader io.Reader = file
	if len(magic) >= 2 && magic[0] == 0x1f && magic[1] == 0x8b {
		gz, err := gzip.NewReader(file)
		if err != nil {
			return err
		}
		defer gz.Close()
		reader = gz
	} else if len(magic) >= 4 && string(magic[:4]) == "\x28\xb5\x2f\xfd" {
		zr, err := zstd.NewReader(file, zstd.WithDecoderConcurrency(1), zstd.WithDecoderMaxMemory(32<<20), zstd.WithDecoderMaxWindow(32<<20))
		if err != nil {
			return err
		}
		defer zr.Close()
		reader = zr
	} else if len(magic) >= 4 && string(magic[:4]) == "KPKG" {
		return errors.New("这是新版 KPKG 二进制格式，当前兼容 tar/gzip/zstd 封装的 .kpkg")
	} else if len(magic) >= 6 && string(magic[:6]) == "\xfd7zXZ\x00" {
		return errors.New("旧版 XZ 安装包需转换为 ZIP、tar.gz 或新版 .kpkg")
	}
	// Limit all decoded bytes, including tar metadata and padding, not only files.
	limited := &io.LimitedReader{R: reader, N: storeMaxExpanded + (8 << 20) + 1}
	tr := tar.NewReader(limited)
	for {
		h, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return fmt.Errorf("无法读取安装包: %w", err)
		}
		if h.Typeflag != tar.TypeReg && h.Typeflag != tar.TypeDir {
			return errors.New("安装包包含链接或特殊文件")
		}
		if err = x.add(h.Name, h.FileInfo().Mode(), h.Size, tr, h.Typeflag == tar.TypeDir); err != nil {
			return err
		}
	}
	if limited.N <= 0 {
		return errors.New("安装包展开后过大")
	}
	// Read to EOF so gzip/zstd checksums and archive trailers are verified too.
	if _, err = io.Copy(io.Discard, limited); err != nil {
		return err
	}
	if limited.N <= 0 {
		return errors.New("安装包展开后过大")
	}
	return nil
}

func storeFindPayload(directory string) (string, string, error) {
	var native, plugins []string
	err := filepath.WalkDir(directory, func(p string, d os.DirEntry, e error) error {
		if e != nil {
			return e
		}
		if d.IsDir() {
			return nil
		}
		if d.Type()&os.ModeSymlink != 0 {
			return errors.New("安装包包含符号链接")
		}
		if d.Name() == "manifest.conf" {
			native = append(native, filepath.Dir(p))
		}
		if d.Name() == "_meta.lua" {
			if info, e := os.Stat(filepath.Join(filepath.Dir(p), "main.lua")); e == nil && info.Mode().IsRegular() {
				plugins = append(plugins, filepath.Dir(p))
			}
		}
		return nil
	})
	if err != nil {
		return "", "", err
	}
	if len(native) == 1 {
		return native[0], "papp", nil
	}
	if len(native) > 1 {
		return "", "", errors.New("安装包包含多个 PaperOS 应用，请分开安装")
	}
	if len(plugins) == 1 {
		return plugins[0], "koplugin", nil
	}
	if len(plugins) > 1 {
		return "", "", errors.New("安装包包含多个 KOReader 插件，请使用单插件安装包")
	}
	return "", "", errors.New("未找到 PaperOS 清单或 KOReader 插件；原厂 Kindle 安装脚本不会直接执行")
}

func storeValidateNative(directory string) (map[string]string, error) {
	manifest, err := readAppManifest(directory)
	if err != nil {
		return nil, err
	}
	count := 0
	var size int64
	err = filepath.WalkDir(directory, func(p string, d os.DirEntry, e error) error {
		if e != nil {
			return e
		}
		if p == directory {
			return nil
		}
		count++
		if count > 256 {
			return errors.New("PaperOS 应用超过 256 个目录项")
		}
		rel, _ := filepath.Rel(directory, p)
		if len(strings.Split(rel, string(filepath.Separator))) > 8 {
			return errors.New("PaperOS 应用嵌套过深")
		}
		info, e := d.Info()
		if e != nil {
			return e
		}
		if !d.IsDir() && !info.Mode().IsRegular() {
			return errors.New("应用包含特殊文件")
		}
		if !d.IsDir() {
			size += info.Size()
			if size > 64<<20 {
				return errors.New("PaperOS 应用超过 64 MiB")
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	program, err := os.Open(filepath.Join(directory, manifest["exec"]))
	if err != nil {
		return nil, err
	}
	defer program.Close()
	header := make([]byte, 52)
	n, _ := bufio.NewReader(program).Read(header)
	if n >= 20 && string(header[:4]) == "\x7fELF" {
		if header[4] != 1 || header[5] != 1 || header[18] != 40 || header[19] != 0 {
			return nil, errors.New("程序不是 ARM 32 位小端版本")
		}
		if n >= 40 && header[37]&4 != 0 {
			return nil, errors.New("程序使用 ARM hard-float，本机需要 soft-float")
		}
	} else if n < 2 || string(header[:2]) != "#!" {
		return nil, errors.New("应用入口必须是 ARM 程序或带 shebang 的脚本")
	}
	return manifest, nil
}

func storeCopyTree(source, target string) error {
	return filepath.WalkDir(source, func(p string, d os.DirEntry, e error) error {
		if e != nil {
			return e
		}
		rel, e := filepath.Rel(source, p)
		if e != nil {
			return e
		}
		dst := filepath.Join(target, rel)
		if d.IsDir() {
			return os.MkdirAll(dst, 0700)
		}
		info, e := d.Info()
		if e != nil {
			return e
		}
		if !info.Mode().IsRegular() {
			return errors.New("不能复制特殊文件")
		}
		in, e := os.Open(p)
		if e != nil {
			return e
		}
		defer in.Close()
		mode := os.FileMode(0600)
		if info.Mode()&0111 != 0 {
			mode = 0700
		}
		out, e := os.OpenFile(dst, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
		if e != nil {
			return e
		}
		_, e = io.Copy(out, in)
		if e == nil {
			e = out.Sync()
		}
		closeErr := out.Close()
		if e != nil {
			return e
		}
		return closeErr
	})
}
