import {fireEvent,render,screen,cleanup} from "@testing-library/react";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import PersistentAdb,{type PersistenceStatus} from "./PersistentAdb";
import {request} from "../../lib/api";
const auth={identity:{role:"administrator"}};
vi.mock("../../lib/auth",()=>({useAuth:()=>auth}));
vi.mock("../../lib/api",()=>({request:vi.fn()}));
afterEach(cleanup);beforeEach(()=>{vi.resetAllMocks();auth.identity.role="administrator";});
const path="/api/v1/devices/device/adb-tcp/persistence";
function status(state:PersistenceStatus["state"],message:string=state):PersistenceStatus{return {state,message,connection_type:"wireless_adb",installed:state!=="not_installed",server_ip:"192.168.0.235",installed_server_ip:null,tcp_port_active:false,key_authorized:false};}
function show(variant:"panel"|"banner"="panel",{online=true,connectionType="wireless_adb"}={}){const client=new QueryClient();render(<QueryClientProvider client={client}><PersistentAdb id="device" connectionType={connectionType} online={online} variant={variant}/></QueryClientProvider>);}
it("warns when not installed and installs after confirmation",async()=>{
 let installed=false;
 vi.mocked(request).mockImplementation(async(_path,options)=>{if(options?.method==="POST")installed=true;return installed?status("persistent","ADB TCP survives reboots"):status("not_installed","Lost after a reboot");});
 show("banner");
 expect(await screen.findByText("ADB connection will not survive a reboot")).toBeInTheDocument();
 fireEvent.click(screen.getByText("Install persistent ADB TCP"));
 expect(screen.getByText("192.168.0.235")).toBeInTheDocument();expect(screen.getByText(/Open shells/)).toBeInTheDocument();
 expect(request).toHaveBeenCalledTimes(1);
 fireEvent.click(screen.getByText("Install and reconnect"));
 await vi.waitFor(()=>expect(request).toHaveBeenCalledWith(path,{method:"POST"}));
 await vi.waitFor(()=>expect(screen.queryByText("ADB connection will not survive a reboot")).not.toBeInTheDocument());
});
it("shows a persistent device as healthy without an action",async()=>{
 vi.mocked(request).mockResolvedValue(status("persistent","ADB TCP on port 5555 is re-enabled after every reboot"));show();
 expect(await screen.findByText("ADB TCP on port 5555 is re-enabled after every reboot")).toBeInTheDocument();
 expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
it("explains root requirements and keeps install failures visible",async()=>{
 vi.mocked(request).mockResolvedValue(status("root_required","Persistent ADB TCP needs root"));show();
 expect(await screen.findByText("Persistent ADB TCP needs root")).toBeInTheDocument();expect(screen.queryByRole("button")).not.toBeInTheDocument();cleanup();
 vi.mocked(request).mockImplementation(async(_path,options)=>{if(options?.method==="POST")throw new Error("Root command was denied");return status("outdated","Installed for a different server");});
 show();fireEvent.click(await screen.findByText("Reinstall persistent ADB TCP"));fireEvent.click(screen.getByText("Install and reconnect"));
 expect(await screen.findByText("Root command was denied")).toBeInTheDocument();
});
it("does not check USB, offline or non-administrator devices",()=>{
 show("panel",{connectionType:"usb"});show("banner",{online:false});auth.identity.role="operator";show();
 expect(request).not.toHaveBeenCalled();
});
