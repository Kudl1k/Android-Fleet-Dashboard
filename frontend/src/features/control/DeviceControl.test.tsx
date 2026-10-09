import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DeviceControl from "./DeviceControl";
import { protectedImage, request } from "../../lib/api";
import OperationsPage from "./OperationsPage";
import AuditPage from "./AuditPage";
const auth={token:"",identity:{identity:"tester",role:"viewer",permissions:[] as string[]},can:(permission:string)=>auth.identity.permissions.includes(permission)};
vi.mock("../../lib/auth",()=>({useAuth:()=>auth}));
vi.mock("../../lib/api",()=>({request:vi.fn(),protectedImage:vi.fn()}));
function show(component:React.ReactNode){render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}>{component}</QueryClientProvider>);}
beforeEach(()=>{vi.clearAllMocks();auth.token="";auth.identity.permissions=["operations.read"];vi.mocked(request).mockResolvedValue({items:[],total:0});HTMLDialogElement.prototype.showModal=vi.fn(function(this:HTMLDialogElement){this.open=true;});});
describe("device control security UX",()=>{
    it("removes captured image previews when credentials change", async () => {
        auth.identity.permissions.push("control.screen");
        vi.mocked(request).mockResolvedValue({items:[{id:"capture",action:"screenshot",state:"succeeded",duration:1,result:{}}],total:1});
        vi.mocked(protectedImage).mockResolvedValue(new Blob(["png"], {type:"image/png"}));
        URL.createObjectURL=vi.fn(()=>"blob:private-preview");
        URL.revokeObjectURL=vi.fn();
        const client = new QueryClient({defaultOptions:{queries:{retry:false}}});
        const wrapper = () => <QueryClientProvider client={client}><DeviceControl id="d1" online/></QueryClientProvider>;
        const view = render(wrapper());
        fireEvent.click(await screen.findByRole("button",{name:"Preview screenshot"}));
        await screen.findByAltText("Captured device screen");
        auth.token="replacement";
        view.rerender(wrapper());
        expect(screen.queryByAltText("Captured device screen")).not.toBeInTheDocument();
        expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:private-preview");
    });
    it("denies viewer controls and audit access",()=>{show(<DeviceControl id="d1" online/>);expect(screen.getByRole("button",{name:"Reboot"})).toBeDisabled();expect(screen.getByRole("button",{name:"Wake screen"})).toBeDisabled();expect(screen.getByLabelText(/Install APK/)).toBeDisabled();});
    it("enables operator screen actions but keeps sensitive controls disabled",()=>{auth.identity.permissions.push("control.screen","control.inspect");show(<DeviceControl id="d1" online/>);expect(screen.getByRole("button",{name:"Wake screen"})).toBeEnabled();expect(screen.getByRole("button",{name:"Reboot"})).toBeDisabled();});
    it("requires explicit confirmation before requesting reboot",async()=>{auth.identity.permissions.push("control.reboot");show(<DeviceControl id="d1" online/>);fireEvent.click(screen.getByRole("button",{name:"Reboot"}));expect(screen.getByRole("dialog",{name:"Confirm reboot"})).toBeInTheDocument();expect(vi.mocked(request).mock.calls.filter(([,options])=>options?.method==="POST")).toHaveLength(0);fireEvent.click(screen.getByRole("button",{name:"Confirm action"}));await waitFor(()=>expect(request).toHaveBeenCalledWith("/api/v1/devices/d1/operations",expect.objectContaining({method:"POST",body:JSON.stringify({action:"reboot",confirmed:true})})));expect(screen.queryByText("Operation succeeded")).not.toBeInTheDocument();});
    it("disables device actions while offline",()=>{auth.identity.permissions.push("control.screen");show(<DeviceControl id="d1" online={false}/>);expect(screen.getByRole("button",{name:"Capture screenshot"})).toBeDisabled();});
    it("requires confirmation before force stop and filters installed packages",async()=>{auth.identity.permissions.push("apps.stop");vi.mocked(request).mockResolvedValue({items:[{id:"a",action:"apps.list",state:"succeeded",duration:1,result:{packages:["com.example.safe","org.example.other"]}}],total:1});show(<DeviceControl id="d1" online/>);await screen.findByText("com.example.safe");fireEvent.change(screen.getByLabelText("Search applications"),{target:{value:"safe"}});expect(screen.queryByText("org.example.other")).not.toBeInTheDocument();fireEvent.click(screen.getByRole("button",{name:"Force-stop"}));expect(screen.getByRole("dialog",{name:"Confirm apps.stop"})).toBeInTheDocument();});
    it("withholds audit and operation requests when permissions are absent",()=>{auth.identity.permissions=[];show(<><OperationsPage/><AuditPage/></>);expect(screen.getByText("Administrator audit access is required.")).toBeInTheDocument();expect(screen.getByText("Authorized operation history access is required.")).toBeInTheDocument();expect(request).not.toHaveBeenCalled();});
});
