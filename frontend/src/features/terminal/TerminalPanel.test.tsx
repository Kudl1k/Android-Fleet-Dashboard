import {fireEvent,render,screen,waitFor,cleanup} from "@testing-library/react";
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
it("starts only on request and disposes terminal and backend session",async()=>{const mounted=render(<TerminalPanel deviceId="d1"/>);expect(request).not.toHaveBeenCalledWith("/api/v1/terminal/sessions",expect.anything());fireEvent.click(screen.getByText("Open ADB Shell"));await waitFor(()=>expect(connections).toHaveLength(1));connections[0].onopen?.();await screen.findByText("active");connections[0].onmessage?.({data:JSON.stringify({version:1,type:"output",data:"\u001b[31mhello"})});expect(write).toHaveBeenCalledWith("\u001b[31mhello");mounted.unmount();expect(connections[0].close).toHaveBeenCalled();expect(dispose).toHaveBeenCalled();await waitFor(()=>expect(request).toHaveBeenCalledWith("/api/v1/terminal/sessions/session",{method:"DELETE"}));});
it("disables offline ADB",()=>{render(<TerminalPanel deviceId="d1" online={false}/>);expect(screen.getByText("Open ADB Shell")).toBeDisabled();});
it("closes malformed transport",async()=>{render(<TerminalPanel deviceId="d1"/>);fireEvent.click(screen.getByText("Open ADB Shell"));await waitFor(()=>expect(connections).toHaveLength(1));connections[0].onmessage?.({data:"not json"});await screen.findByText("Invalid terminal response");expect(connections[0].close).toHaveBeenCalled();});
it("hides terminals without view permission",()=>{auth.can=()=>false;render(<TerminalPanel deviceId="d1"/>);expect(screen.queryByText("Terminal")).not.toBeInTheDocument();});
it("supports simultaneous tabs, bounded input, resize and timeout notices",async()=>{render(<TerminalPanel deviceId="d1"/>);fireEvent.click(screen.getByText("Open ADB Shell"));await waitFor(()=>expect(connections).toHaveLength(1));connections[0].onopen?.();const input=onData.mock.calls[0][0] as (data:string)=>void;input("x".repeat(4097));expect(connections[0].send.mock.calls.filter(c=>JSON.parse(c[0]).type==="input")).toHaveLength(2);expect(connections[0].send).toHaveBeenCalledWith(JSON.stringify({version:1,type:"resize",cols:80,rows:24}));fireEvent.click(screen.getByText("Open ADB Shell"));await waitFor(()=>expect(connections).toHaveLength(2));expect(screen.getAllByRole("tab")).toHaveLength(2);connections[1].onmessage?.({data:JSON.stringify({version:1,type:"status",state:"timed_out",reason:"Idle timeout"})});await screen.findByText("Idle timeout");expect(screen.getByText("timed out")).toBeInTheDocument();});

it("bounds Unicode and escaped control input by serialized UTF8 bytes",()=>{const data=("😀\u0000\u001b\"\\").repeat(3000);const chunks=chunkTerminalInput(data);expect(chunks.join("")).toBe(data);for(const chunk of chunks){expect(new TextEncoder().encode(JSON.stringify({version:1,type:"input",data:chunk})).byteLength).toBeLessThanOrEqual(4096);expect(chunk).not.toMatch(/[\uD800-\uDBFF]$/);}});

it("awaits previous session cleanup before reconnecting at capacity",async()=>{
 let finishCleanup!:()=>void;const delayed=new Promise<void>(resolve=>{finishCleanup=resolve;});
 vi.mocked(request).mockImplementation(async(path,options)=>{
  if(options?.method==="DELETE")return delayed;
  if(path.endsWith("/profiles"))return [];
  if(path.endsWith("/ticket"))return {ticket:"one-use",protocol:"fleet-terminal.v1"};
  return {id:"session"};
 });
 render(<TerminalPanel deviceId="d1"/>);fireEvent.click(screen.getByText("Open ADB Shell"));await waitFor(()=>expect(connections).toHaveLength(1));
 fireEvent.click(screen.getByText("Reconnect"));await waitFor(()=>expect(request).toHaveBeenCalledWith("/api/v1/terminal/sessions/session",{method:"DELETE"}));
 expect(vi.mocked(request).mock.calls.filter(call=>call[0]==="/api/v1/terminal/sessions")).toHaveLength(1);
 finishCleanup();await waitFor(()=>expect(connections).toHaveLength(2));
 expect(vi.mocked(request).mock.calls.filter(call=>call[0]==="/api/v1/terminal/sessions")).toHaveLength(2);
});
