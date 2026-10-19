// Read-only connection checks. Never prints credentials or invokes HA services.
package main

import (
 "bufio"
 "context"
 "encoding/json"
 "fmt"
 "io"
 "net"
 "net/http"
 "net/url"
 "os"
 "sync"
 "time"
)

type config struct { BaseURL, Token, RefreshToken string; Items []struct{ Entity string } }
type portCheck struct { Target string; Connected bool; ProxyStatus int }
type requestCheck struct { Method, Path string; Status int }
type bufferedConn struct { net.Conn; reader *bufio.Reader }
func(c *bufferedConn) Read(p []byte)(int,error){return c.reader.Read(p)}

func connect(address string, timeout time.Duration)(net.Conn,int,error){
 c,e:=net.DialTimeout("tcp","127.0.0.1:1055",timeout);if e!=nil{return nil,0,e}
 c.SetDeadline(time.Now().Add(timeout))
 request:=&http.Request{Method:"CONNECT",URL:&url.URL{Opaque:address},Host:address}
 if e=request.Write(c);e!=nil{c.Close();return nil,0,e}
 reader:=bufio.NewReader(c);r,e:=http.ReadResponse(reader,request)
 if e!=nil{c.Close();return nil,0,e}
 if r.StatusCode!=200{c.Close();return nil,r.StatusCode,fmt.Errorf("connection refused")}
 c.SetDeadline(time.Time{});return &bufferedConn{c,reader},200,nil
}
func main(){
 data,e:=os.ReadFile("/var/lib/paperos/services/mihome.json");var cfg config
 if e!=nil||json.Unmarshal(data,&cfg)!=nil||len(cfg.Items)<1||len(cfg.Items)>12{fmt.Println(`{"error":"invalid_config"}`);os.Exit(1)}
 endpoints:=[]string{"192.0.2.10:8787","192.0.2.10:9999","192.0.2.10:8123","192.0.2.10:445","192.0.2.10:139","192.0.2.10:22","192.0.2.10:2049","192.0.2.10:111","192.0.2.10:80","192.0.2.10:443","192.0.2.30:9999","192.0.2.30:445"}
 ports:=make([]portCheck,len(endpoints));var group sync.WaitGroup
 for i,endpoint:=range endpoints{group.Add(1);go func(i int,address string){defer group.Done();c,status,e:=connect(address,4*time.Second);ports[i]=portCheck{address,e==nil,status};if c!=nil{c.Close()}}(i,endpoint)}
 transport:=http.DefaultTransport.(*http.Transport).Clone();transport.Proxy=nil
 transport.DialContext=func(ctx context.Context,network,address string)(net.Conn,error){c,_,e:=connect(address,6*time.Second);return c,e}
 client:=&http.Client{Transport:transport,Timeout:8*time.Second,CheckRedirect:func(*http.Request,[]*http.Request)error{return http.ErrUseLastResponse}}
 checks:=[]requestCheck{}
 paths:=[]struct{method,path string}{{"GET","/api/states/"+cfg.Items[0].Entity},{"GET","/api/states/sensor.paperos_unselected_security_probe"},{"GET","/api/config"},{"GET","/desktop/"},{"GET","/scope.json"},{"POST","/api/states/"+cfg.Items[0].Entity},{"POST","/api/services/paperos_security_probe/no_such_service"}}
 for _,test:=range paths{request,_:=http.NewRequest(test.method,cfg.BaseURL+test.path,nil);request.Header.Set("Authorization","Bearer "+cfg.Token);r,e:=client.Do(request);status:=0;if e==nil{status=r.StatusCode;io.Copy(io.Discard,io.LimitReader(r.Body,65536));r.Body.Close()};checks=append(checks,requestCheck{test.method,test.path,status})}
 group.Wait();transport.CloseIdleConnections()
 json.NewEncoder(os.Stdout).Encode(struct{ Ports []portCheck; Requests []requestCheck; HARefreshCredentialPresent bool; GatewayConfigured bool }{ports,checks,cfg.RefreshToken!="",cfg.BaseURL=="http://192.0.2.10:8787"})
}
