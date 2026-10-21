import {fireEvent,render,screen,waitFor,cleanup,within} from "@testing-library/react";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import TerminalPanel, {chunkTerminalInput} from "./TerminalPanel";
import {request} from "../../lib/api";
const auth={token:"token",identity:{},can:()=>true};
const write=vi.fn(),dispose=vi.fn(),onData=vi.fn();
vi.mock("../../lib/auth",()=>({useAuth:()=>auth}));vi.mock("../../lib/api",()=>({request:vi.fn()}));
vi.mock("@xterm/xterm",()=>({Terminal:class {cols=80;rows=24;options={};loadAddon=vi.fn();open=vi.fn();onData=onData.mockReturnValue({dispose:vi.fn()});attachCustomKeyEventHandler=vi.fn();write=write;dispose=dispose;clear=vi.fn();getSelection=()=>"selected";}}));vi.mock("@xterm/addon-fit",()=>({FitAddon:class{fit=vi.fn();}}));
class Socket{static OPEN=1;readyState=1;onopen:(()=>void)|null=null;onmessage:((event:{data:string})=>void)|null=null;onclose:(()=>void)|null=null;onerror:(()=>void)|null=null;send=vi.fn();close=vi.fn();constructor(){connections.push(this);}}
let connections:Socket[]=[];
beforeEach(()=>{vi.clearAllMocks();connections=[];auth.can=()=>true;vi.stubGlobal("WebSocket",Socket);vi.stubGlobal("ResizeObserver",class{observe(){}disconnect(){}});vi.mocked(request).mockImplementation(async path=>path.endsWith("/profiles")?[]:path.endsWith("/ticket")?{ticket:"one-use",protocol:"fleet-terminal.v1"}:{id:"session"});});afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it("starts only on request and detaches terminal without terminating backend session",async()=>{const mounted=render(<TerminalPanel deviceId="d1"/>);expect(request).not.toHaveBeenCalledWith("/api/v1/terminal/sessions",expect.anything());fireEvent.click(screen.getByText("Open ADB Shell"));await waitFor(()=>expect(connections).toHaveLength(1));connections[0].onopen?.();await screen.findByText("active");connections[0].onmessage?.({data:JSON.stringify({version:1,type:"output",data:"\u001b[31mhello"})});expect(write).toHaveBeenCalledWith("\u001b[31mhello");mounted.unmount();expect(connections[0].close).toHaveBeenCalled();expect(dispose).toHaveBeenCalled();expect(request).not.toHaveBeenCalledWith("/api/v1/terminal/sessions/session",{method:"DELETE"});});
it("disables offline ADB",()=>{render(<TerminalPanel deviceId="d1" online={false}/>);expect(screen.getByText("Open ADB Shell")).toBeDisabled();});
it("closes malformed transport",async()=>{render(<TerminalPanel deviceId="d1"/>);fireEvent.click(screen.getByText("Open ADB Shell"));await waitFor(()=>expect(connections).toHaveLength(1));connections[0].onmessage?.({data:"not json"});await screen.findByText("Invalid terminal response");expect(connections[0].close).toHaveBeenCalled();});
it("hides terminals without view permission",()=>{auth.can=()=>false;render(<TerminalPanel deviceId="d1"/>);expect(screen.queryByText("Terminal")).not.toBeInTheDocument();});
it("supports simultaneous tabs, bounded input, resize and timeout notices",async()=>{render(<TerminalPanel deviceId="d1"/>);fireEvent.click(screen.getByText("Open ADB Shell"));await waitFor(()=>expect(connections).toHaveLength(1));connections[0].onopen?.();const input=onData.mock.calls[0][0] as (data:string)=>void;input("x".repeat(4097));expect(connections[0].send.mock.calls.filter(c=>JSON.parse(c[0]).type==="input")).toHaveLength(2);expect(connections[0].send).toHaveBeenCalledWith(JSON.stringify({version:1,type:"resize",cols:80,rows:24}));fireEvent.click(screen.getByText("Open ADB Shell"));await waitFor(()=>expect(connections).toHaveLength(2));expect(screen.getAllByRole("tab")).toHaveLength(2);connections[1].onmessage?.({data:JSON.stringify({version:1,type:"status",state:"timed_out",reason:"Idle timeout"})});await screen.findByText("Idle timeout");expect(screen.getByText("timed out")).toBeInTheDocument();});

it("bounds Unicode and escaped control input by serialized UTF8 bytes",()=>{const data=("😀\u0000\u001b\"\\").repeat(3000);const chunks=chunkTerminalInput(data);expect(chunks.join("")).toBe(data);for(const chunk of chunks){expect(new TextEncoder().encode(JSON.stringify({version:1,type:"input",data:chunk})).byteLength).toBeLessThanOrEqual(4096);expect(chunk).not.toMatch(/[\uD800-\uDBFF]$/);}});

it("reattaches the same session on reconnect",async()=>{
 render(<TerminalPanel deviceId="d1"/>);fireEvent.click(screen.getByText("Open ADB Shell"));await waitFor(()=>expect(connections).toHaveLength(1));
 fireEvent.click(screen.getByText("Reconnect"));await waitFor(()=>expect(connections).toHaveLength(2));
 expect(vi.mocked(request).mock.calls.filter(call=>call[0]==="/api/v1/terminal/sessions"&&call[1]?.method==="POST")).toHaveLength(1);
});


it("opens independent tabs over HTTP without crypto.randomUUID",async()=>{
 vi.stubGlobal("crypto",{});
 render(<TerminalPanel deviceId="d1"/>);
 fireEvent.click(screen.getByText("Open ADB Shell"));
 await waitFor(()=>expect(connections).toHaveLength(1));
 fireEvent.click(screen.getByText("Open ADB Shell"));
 await waitFor(()=>expect(connections).toHaveLength(2));
 expect(screen.getAllByRole("tab")).toHaveLength(2);
 fireEvent.click(screen.getAllByText("Close session")[0]);
 await waitFor(()=>expect(screen.getAllByRole("tab")).toHaveLength(1));
});

it("starts a recorded SSH command",async()=>{
 render(<TerminalPanel initialProfile={{id:"ssh1",name:"Host",host:"host",port:22,username:"user",enabled:true,auth_method:"key"}}/>);
 fireEvent.change(screen.getByLabelText("Program command"),{target:{value:"python3 benchmark.py"}});
 fireEvent.click(screen.getByText("Record run"));
 await waitFor(()=>expect(request).toHaveBeenCalledWith("/api/v1/terminal/sessions",expect.objectContaining({method:"POST",body:JSON.stringify({connection_type:"ssh",profile_id:"ssh1",command:"python3 benchmark.py",cols:80,rows:24})})));
});


it("closes a detached session directly from history",async()=>{
 vi.mocked(request).mockImplementation(async(path,options)=>{
  if(path==="/api/v1/terminal/sessions"&&!options?.method)return {items:[{id:"detached",connection_type:"ssh",state:"active"}]};
  if(path.endsWith("/profiles"))return [];
  return {};
 });
 render(<TerminalPanel/>);
 const history = await screen.findByRole("region", {name: "Sessions and recorded results"});
 await within(history).findByText("active");
 fireEvent.click(within(history).getByText("ssh"));
 fireEvent.click(screen.getByText("Close session"));
 await waitFor(()=>expect(request).toHaveBeenCalledWith("/api/v1/terminal/sessions/detached",{method:"DELETE"}));
 await within(history).findByText("closed");
 expect(screen.queryByText("Resume session")).not.toBeInTheDocument();
});

it("records linked device statistics at a 15 second interval",async()=>{
 render(<TerminalPanel initialProfile={{id:"ssh1",name:"Host",host:"host",port:22,username:"user",enabled:true,auth_method:"key",device_id:"phone"}}/>);
 fireEvent.change(screen.getByLabelText("Program command"),{target:{value:"benchmark"}});
 expect(screen.getByLabelText("Record device statistics (15 seconds)")).toBeChecked();
 fireEvent.click(screen.getByText("Record run"));
 await waitFor(()=>expect(request).toHaveBeenCalledWith("/api/v1/terminal/sessions",expect.objectContaining({body:JSON.stringify({connection_type:"ssh",profile_id:"ssh1",command:"benchmark",record_device:true,sample_interval:15,cols:80,rows:24})})));
});

it("keeps connection methods named and closes a session only from its own tools", async () => {
 render(<TerminalPanel deviceId="d1" />);
 const adb = screen.getByRole("group", {name: "ADB shell"});
 expect(within(screen.getByRole("group", {name: "SSH connection"})).getByRole("combobox", {name: "SSH connection"})).toBeInTheDocument();
 fireEvent.click(within(adb).getByRole("button", {name: "Open ADB Shell"}));
 await waitFor(()=>expect(connections).toHaveLength(1));
 const tools = screen.getByRole("group", {name: "Terminal session tools"});
 expect(within(tools).getByRole("button", {name: "Copy selection"})).toBeInTheDocument();
 expect(within(tools).queryByRole("button", {name: "Close session"})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole("button", {name: "Close session"}));
 await waitFor(()=>expect(request).toHaveBeenCalledWith("/api/v1/terminal/sessions/session", {method: "DELETE"}));
});

it("filters device session history without starting or closing sessions", async () => {
 vi.mocked(request).mockImplementation(async path=>path.endsWith("/profiles") ? [] : {items: [{id:"one",device_id:"d1",connection_type:"ssh",command:"python benchmark-with-a-long-command.py",state:"closed"},{id:"two",device_id:"d1",connection_type:"adb",state:"active"},{id:"other",device_id:"d2",connection_type:"ssh",state:"active"}]});
 render(<TerminalPanel deviceId="d1" />);
 const region=screen.getByRole("region", {name:"Sessions and recorded results"});
 await within(region).findByText("python benchmark-with-a-long-command.py");
 expect(within(region).queryByText("other")).not.toBeInTheDocument();
 expect(within(region).queryByRole("searchbox")).not.toBeInTheDocument();
 fireEvent.change(screen.getByLabelText("Search sessions"), {target:{value:"benchmark"}});
 expect(within(region).getAllByRole("listitem")).toHaveLength(1);
 fireEvent.click(within(region).getByText("python benchmark-with-a-long-command.py"));
 expect(within(region).getByRole("button", {name:"Download results"})).toBeInTheDocument();
 fireEvent.change(screen.getByLabelText("Search sessions"), {target:{value:"no-match"}});
 expect(within(region).getByText("No sessions match this search.")).toBeInTheDocument();
 expect(vi.mocked(request).mock.calls.some(([, options])=>options?.method==="POST"||options?.method==="DELETE")).toBe(false);
});

it("distinguishes a failed session-history request from an empty history", async () => {
 vi.mocked(request).mockImplementation(async path=>{if(path==="/api/v1/terminal/sessions")throw new Error("History request failed");return [];});
 render(<TerminalPanel deviceId="d1" />);
 expect(screen.getByText("Loading session history…")).toBeInTheDocument();
 expect(await screen.findByRole("alert")).toHaveTextContent("History request failed");
 expect(screen.queryByText("No sessions or recorded results for this device.")).not.toBeInTheDocument();
});
