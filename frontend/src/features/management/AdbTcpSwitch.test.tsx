import {fireEvent,render,screen,cleanup,waitFor} from "@testing-library/react";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import AdbTcpSwitch from "./AdbTcpSwitch";
import {request} from "../../lib/api";
const auth={identity:{role:"admin"}};
vi.mock("../../lib/auth",()=>({useAuth:()=>auth}));
vi.mock("../../lib/api",()=>({request:vi.fn()}));
afterEach(cleanup);beforeEach(()=>{vi.resetAllMocks();auth.identity.role="admin";});
function show(online=true){const client=new QueryClient();const invalidate=vi.spyOn(client,"invalidateQueries");render(<QueryClientProvider client={client}><AdbTcpSwitch id="device" online={online}/></QueryClientProvider>);return invalidate;}
it("confirms before switching and refreshes the existing device",async()=>{
 vi.mocked(request).mockResolvedValue({id:"device",port:5555,state:"online"});const invalidate=show();
 fireEvent.click(screen.getByText("Switch to ADB TCP"));expect(request).not.toHaveBeenCalled();
 expect(screen.getByText(/may close open shells/)).toBeInTheDocument();
 fireEvent.click(screen.getByText("Enable TCP and reconnect"));
 await screen.findByText("ADB TCP enabled on port 5555.");
 expect(request).toHaveBeenCalledWith("/api/v1/devices/device/adb-tcp",{method:"POST"});expect(invalidate).toHaveBeenCalled();
});
it("shows failures and allows retry",async()=>{
 vi.mocked(request).mockRejectedValue(new Error("TCP switch timed out"));show();
 fireEvent.click(screen.getByText("Switch to ADB TCP"));fireEvent.click(screen.getByText("Enable TCP and reconnect"));
 await screen.findByRole("alert");expect(screen.getByText("TCP switch timed out")).toBeInTheDocument();
 await waitFor(()=>expect(screen.getByText("Enable TCP and reconnect")).toBeEnabled());
});
it("disables offline devices and hides privileged action from operators",()=>{
 show(false);expect(screen.getByText("Switch to ADB TCP")).toBeDisabled();cleanup();
 auth.identity.role="operator";show();expect(screen.queryByText("Switch to ADB TCP")).not.toBeInTheDocument();
});
it("can cancel without changing the device",()=>{show();fireEvent.click(screen.getByText("Switch to ADB TCP"));fireEvent.click(screen.getByText("Cancel"));expect(request).not.toHaveBeenCalled();expect(screen.queryByText("Enable TCP and reconnect")).not.toBeInTheDocument();});
