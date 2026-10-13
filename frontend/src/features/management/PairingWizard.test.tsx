import { fireEvent,render,screen,cleanup } from "@testing-library/react";
import { QueryClient,QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach,beforeEach,expect,it,vi } from "vitest";
import PairingWizard from "./PairingWizard";
import {request} from "../../lib/api";
const auth={identity:{role:"admin"}};
vi.mock("../../lib/auth",()=>({useAuth:()=>auth}));vi.mock("../../lib/api",()=>({request:vi.fn()}));
afterEach(cleanup);beforeEach(()=>{vi.resetAllMocks();auth.identity.role="admin";});
function show(){render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><PairingWizard/></MemoryRouter></QueryClientProvider>);}
function fill(){fireEvent.click(screen.getByText("Start pairing"));fireEvent.change(screen.getByLabelText("Device IP address"),{target:{value:"192.168.1.8"}});fireEvent.change(screen.getByLabelText("Pairing port"),{target:{value:"34567"}});fireEvent.change(screen.getByLabelText("Six-digit pairing code"),{target:{value:"123456"}});}
it("pairs separately and retries connection without sending pairing secrets",async()=>{vi.mocked(request).mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("Connection refused")).mockResolvedValueOnce({serial:"device",model:"Samsung",android_version:"15"});show();fill();fireEvent.click(screen.getByText("Pair device"));await screen.findByLabelText("Wireless Debugging connection port");fireEvent.change(screen.getByLabelText("Wireless Debugging connection port"),{target:{value:"45678"}});fireEvent.click(screen.getByText("Connect and verify"));await screen.findByText("Connection refused");fireEvent.click(screen.getByText("Connect and verify"));await screen.findByLabelText("Friendly device name");expect(vi.mocked(request).mock.calls.map(c=>c[0])).toEqual(["/api/v1/pairing/pair","/api/v1/pairing/connect","/api/v1/pairing/connect"]);expect(JSON.parse(vi.mocked(request).mock.calls[1][1]!.body as string)).toEqual({host:"192.168.1.8",port:45678});});
it("clears pairing code after failure",async()=>{vi.mocked(request).mockRejectedValue(new Error("Pairing failed"));show();fill();fireEvent.click(screen.getByText("Pair device"));await screen.findByText("Pairing failed");expect(screen.getByLabelText("Six-digit pairing code")).toHaveValue("");});
it("hides pairing controls from operators",()=>{auth.identity.role="operator";show();expect(screen.queryByText("Add Android Device")).not.toBeInTheDocument();});
