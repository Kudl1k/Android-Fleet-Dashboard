import { useQuery } from "@tanstack/react-query";
import { request } from "../../lib/api";
export interface Operation { id:string; device_id:string; action:string; actor:string; role:string; state:string; created_at:number; started_at:number|null; finished_at:number|null; duration:number|null; result:Record<string,unknown>|null; error:string|null; cancellable:boolean }
export interface Page<T> {items:T[];total:number}
export const active = (op:Operation)=>["queued","running"].includes(op.state);
export function useOperations(params:URLSearchParams, enabled=true) {return useQuery({queryKey:["operations",params.toString()],queryFn:({signal})=>request<Page<Operation>>(`/api/v1/operations?${params}`,{signal}),enabled,refetchInterval:2000});}
export const operationPermission = (action:string) => ({state:"control.inspect",properties:"control.inspect","apps.list":"control.inspect","apps.inspect":"control.inspect","screen.wake":"control.screen","screen.lock":"control.screen",screenshot:"control.screen",reboot:"control.reboot","reboot.recovery":"control.reboot_special","reboot.bootloader":"control.reboot_special","apps.restore":"apps.install","apps.cleanup":"apps.uninstall"} as Record<string,string>)[action] ?? action;
