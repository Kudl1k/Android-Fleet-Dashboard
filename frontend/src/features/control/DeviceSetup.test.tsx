import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import DeviceSetup from "./DeviceSetup";
import {request} from "../../lib/api";
import type {Operation} from "./operations";
const auth={can:()=>true};
const operations:{data:{items:Operation[]}}={data:{items:[]}};
vi.mock("../../lib/auth",()=>({useAuth:()=>auth}));
vi.mock("../../lib/api",()=>({request:vi.fn()}));
vi.mock("./operations",()=>({useOperations:()=>operations,active:(op:Operation)=>["queued","running"].includes(op.state)}));
beforeEach(()=>{vi.clearAllMocks();auth.can=()=>true;operations.data.items=[];HTMLDialogElement.prototype.showModal=vi.fn();});afterEach(cleanup);
function operation(values:Partial<Operation>):Operation{return {id:"job",device_id:"device",action:"setup.termux",actor:"admin",role:"administrator",state:"running",created_at:0,started_at:0,finished_at:null,duration:0,result:null,error:null,cancellable:false,...values};}
function show(online=true){const client=new QueryClient();render(<QueryClientProvider client={client}><DeviceSetup id="device" online={online}/></QueryClientProvider>);return client;}
it("requires confirmation before installing apps and SSH",async()=>{
 vi.mocked(request).mockResolvedValue({id:"job"});show();
 fireEvent.click(screen.getByText("Install F-Droid, Termux & SSH"));
 expect(request).not.toHaveBeenCalled();expect(screen.getByText(/restarts Termux SSH/)).toBeInTheDocument();
 fireEvent.click(screen.getByText("Confirm setup"));
 await waitFor(()=>expect(request).toHaveBeenCalledWith("/api/v1/devices/device/operations",{method:"POST",body:JSON.stringify({action:"setup.termux",confirmed:true})}));
});
it("can resume SSH configuration without reinstalling applications",async()=>{
 vi.mocked(request).mockResolvedValue({id:"job"});show();fireEvent.click(screen.getByText("Enable Termux SSH"));fireEvent.click(screen.getByText("Confirm setup"));
 await waitFor(()=>expect(request).toHaveBeenCalledWith("/api/v1/devices/device/operations",{method:"POST",body:JSON.stringify({action:"setup.ssh",confirmed:true})}));
});
it("hides privileged setup controls and disables offline devices",()=>{auth.can=()=>false;show();expect(screen.queryByText("Install F-Droid, Termux & SSH")).not.toBeInTheDocument();cleanup();auth.can=()=>true;show(false);expect(screen.getByText("Install F-Droid, Termux & SSH")).toBeDisabled();});
it("shows actual progress and actionable partial failures",()=>{
 operations.data.items=[operation({state:"failed",result:{stage:"Installing OpenSSH"},error:"Open Termux and retry Enable Termux SSH"})];show();
 expect(screen.getByRole("status")).toHaveTextContent("Installing OpenSSH");expect(screen.getByRole("alert")).toHaveTextContent("Open Termux and retry");
});
it("does not present queued work as verified SSH",()=>{operations.data.items=[operation({state:"running",result:{stage:"Opening Termux"}})];show();expect(screen.getByText("Enable Termux SSH")).toBeDisabled();expect(screen.queryByText(/SSH login verified as/)).not.toBeInTheDocument();});
