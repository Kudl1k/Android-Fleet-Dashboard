import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { request } from "../../lib/api";
import { useAuth } from "../../lib/auth";

export default function AdbTcpSwitch({id, online}:{id:string; online:boolean}) {
 const auth=useAuth(); const client=useQueryClient();
 const [confirm,setConfirm]=useState(false); const [busy,setBusy]=useState(false);
 const [error,setError]=useState(""); const [done,setDone]=useState(false);
 if(!["admin","administrator"].includes(auth.identity?.role??""))return null;
 const run=async()=>{setBusy(true);setError("");try{
  await request(`/api/v1/devices/${id}/adb-tcp`,{method:"POST"});
  setDone(true);setConfirm(false);
 }catch(err){setError(err instanceof Error?err.message:"TCP switch failed");}
 finally{setBusy(false);await client.invalidateQueries();}};
 return <div>{done?<p role="status">ADB TCP enabled on port 5555.</p>:<button disabled={!online||busy} onClick={()=>setConfirm(true)}>Switch to ADB TCP</button>}
 {confirm&&<div><p>Switch this device to ADB TCP on port 5555? This may close open shells. Its name and history are preserved. Use a trusted network; TCP mode may need enabling again after reboot.</p>
 <button disabled={busy} onClick={()=>void run()}>{busy?"Switching…":"Enable TCP and reconnect"}</button>
 <button disabled={busy} onClick={()=>setConfirm(false)}>Cancel</button></div>}
 {error&&<p role="alert">{error}</p>}</div>;
}
