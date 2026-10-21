import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    it("separates restart actions from inspection and screen power without bypassing confirmation", () => {
        auth.identity.permissions.push("control.inspect", "control.screen", "control.reboot");
        show(<DeviceControl id="d1" online />);
        const inspection = screen.getByRole("group", {name: "Inspect device"});
        expect(within(inspection).getByRole("button", {name: "Capture screenshot"})).toBeInTheDocument();
        expect(within(inspection).queryByRole("button", {name: "Reboot"})).not.toBeInTheDocument();
        expect(within(screen.getByRole("group", {name: "Screen power"})).getByRole("button", {name: "Wake screen"})).toBeEnabled();
        fireEvent.click(within(screen.getByRole("group", {name: "Restart device"})).getByRole("button", {name: "Reboot"}));
        expect(screen.getByRole("dialog", {name: "Confirm reboot"})).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", {name: "Cancel"}));
        expect(vi.mocked(request).mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
    });
    it("announces a pending device request and prevents duplicate actions", async () => {
        auth.identity.permissions.push("control.inspect");
        vi.mocked(request).mockImplementation(async (_path, options) => options?.method === "POST" ? new Promise(() => {}) : {items: [], total: 0});
        show(<DeviceControl id="d1" online />);
        const inspect = screen.getByRole("button", {name: "Inspect state"});
        fireEvent.click(inspect);
        expect(await screen.findByText("Requesting device action…")).toBeInTheDocument();
        expect(inspect).toHaveAttribute("aria-busy", "true");
        expect(inspect).toBeDisabled();
        fireEvent.click(inspect);
        expect(vi.mocked(request).mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
    });
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

it("keeps application search outside the named list and distinguishes no matches", async () => {
    vi.mocked(request).mockResolvedValue({items: [{id: "apps", action: "apps.list", state: "succeeded", duration: null, result: {packages: ["com.example.long.application.identifier", "org.example.second"]}}], total: 1});
    show(<DeviceControl id="d1" online />);
    const region = screen.getByRole("region", {name: "Installed applications"});
    await within(region).findByText("org.example.second");
    expect(region).toHaveAttribute("tabindex", "0");
    expect(within(region).queryByRole("searchbox")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search applications"), {target: {value: "not-installed"}});
    expect(within(region).getByText("No applications match this search.")).toBeInTheDocument();
    expect(screen.getByText("0 of 2 loaded")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search applications"), {target: {value: ""}});
    expect(screen.getByRole("region", {name: "Installed applications"})).toBe(region);
    expect(within(region).getAllByRole("row")).toHaveLength(3);
});
it("preserves zero durations and explicitly identifies unavailable durations in operations", async () => {
    vi.mocked(request).mockResolvedValue({items: [{id: "zero", action: "state", state: "succeeded", duration: 0, result: null}, {id: "missing", action: "properties", state: "failed", duration: null, result: null}], total: 2});
    show(<DeviceControl id="d1" online />);
    const region = screen.getByRole("region", {name: "Recent device operations"});
    expect(await within(region).findByText("state")).toBeInTheDocument();
    const items = within(region).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("0.00 s");
    expect(items[1]).toHaveTextContent("Duration: Unavailable");
    expect(within(region).queryByRole("heading")).not.toBeInTheDocument();
});
