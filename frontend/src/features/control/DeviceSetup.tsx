import {useState} from "react";
import {useQueryClient} from "@tanstack/react-query";
import {request} from "../../lib/api";
import {useAuth} from "../../lib/auth";
import Confirmation from "../management/Confirmation";
import {active,useOperations,type Operation} from "./operations";

export default function DeviceSetup({id,online}:{id:string;online:boolean}) {
 const auth=useAuth();const client=useQueryClient();
 const allowed=auth.can("apps.install")&&auth.can("terminal:profile:manage");
 const operations=useOperations(new URLSearchParams({device_id:id,limit:"30"}),allowed);
 const [confirm,setConfirm]=useState<"setup.termux"|"setup.ssh"|null>(null);
 const [busy,setBusy]=useState(false);const [error,setError]=useState("");
 const running=operations.data?.items.some(active)??false;
 const setup=operations.data?.items.find(op=>op.action.startsWith("setup."));
 async function start(){if(!confirm)return;setBusy(true);setError("");try{
  await request<Operation>(`/api/v1/devices/${encodeURIComponent(id)}/operations`,{method:"POST",body:JSON.stringify({action:confirm,confirmed:true})});
  setConfirm(null);await client.invalidateQueries({queryKey:["operations"]});
 }catch(err){setError(err instanceof Error?err.message:"Setup could not start");}finally{setBusy(false);}}
 if(!allowed)return null;
 return <section className="panel"><h2>F-Droid, Termux &amp; SSH</h2>
 <p>Install F-Droid and Termux, then enable SSH on port 8022 with a key managed by this dashboard. No root is required. Fleet monitoring continues over ADB.</p>
 <p>Keep the device unlocked and Termux visible during setup. Approve any Android prompts and wait for its shell prompt. Setup can take several minutes.</p>
 <div className="actions"><button disabled={!online||busy||running} onClick={()=>setConfirm("setup.termux")}>Install F-Droid, Termux &amp; SSH</button>
 <button disabled={!online||busy||running} onClick={()=>setConfirm("setup.ssh")}>Enable Termux SSH</button></div>
 {error&&<p role="alert" className="error">{error}</p>}
 {setup&&<div><p role="status">{setup.state} · {String(setup.result?.stage??"Device setup")}</p>
 {setup.error&&<p role="alert" className="error">{setup.error}</p>}
 {setup.state==="succeeded"&&typeof setup.result?.profile_id==="string"&&<p>SSH login verified as <code>{String(setup.result.username)}</code> on port 8022. Select <strong>Termux SSH</strong> in this device’s Terminal panel to connect.</p>}</div>}
 {confirm&&<Confirmation title={confirm==="setup.termux"?"Install apps and enable SSH":"Enable Termux SSH"} onCancel={()=>{if(!busy)setConfirm(null);}}>
 <p>{confirm==="setup.termux"?"Downloads verified APKs from F-Droid and installs missing apps. Existing apps and their data are kept. ":"Uses the installed Termux app. "}Setup types a configuration script into the foreground Termux terminal. Leave it at an idle shell prompt and do not type or switch apps while setup runs.</p>
 <p>This installs OpenSSH, authorizes a dashboard-managed key, disables SSH password login and restarts Termux SSH on port 8022. Existing Termux SSH sessions will close. Android may stop the server after reboot or in the background.</p>
 <button disabled={busy} onClick={()=>setConfirm(null)}>Cancel</button><button disabled={busy} onClick={()=>void start()}>{busy?"Starting…":"Confirm setup"}</button>
 </Confirmation>}
 </section>;
}
