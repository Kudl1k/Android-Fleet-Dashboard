import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { protectedImage, request } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import Confirmation from "../management/Confirmation";
import { active, operationPermission, useOperations, type Operation } from "./operations";
export default function DeviceControl(props:{id:string;online:boolean}) {
    const auth = useAuth();
    return <DeviceControlSession key={`${props.id}:${auth.token}`} {...props} />;
}
function DeviceControlSession({id,online}:{id:string;online:boolean}) {
    const auth=useAuth(); const client=useQueryClient();
    const [search,setSearch]=useState(""); const [confirm,setConfirm]=useState<{action:string;package?:string}|null>(null);
    const [preview,setPreview]=useState<{url:string;id:string}|null>(null); const [imageError,setImageError]=useState("");
    const operations=useOperations(new URLSearchParams({device_id:id,limit:"30"}),auth.can("operations.read"));
    const mutation=useMutation({mutationFn:(body:{action:string;package?:string;confirmed?:boolean})=>request<Operation>(`/api/v1/devices/${encodeURIComponent(id)}/operations`,{method:"POST",body:JSON.stringify(body)}),onSuccess:()=>client.invalidateQueries({queryKey:["operations"]})});
    const upload=useMutation({mutationFn:(file:File)=>request<Operation>(`/api/v1/devices/${encodeURIComponent(id)}/apk`,{method:"POST",headers:{"Content-Type":"application/vnd.android.package-archive"},body:file}),onSuccess:()=>client.invalidateQueries({queryKey:["operations"]})});
    const busy=mutation.isPending||upload.isPending||Boolean(operations.data?.items.some(active));
    const allowed=(action:string)=>auth.can(operationPermission(action));
    const list=operations.data?.items.find(op=>op.action==="apps.list"&&op.state==="succeeded");
    const raw=list?.result?.packages ?? list?.result?.applications ?? [];
    const packages=Array.isArray(raw)?raw.map(item=>typeof item==="string"?item:String((item as {package?:string;name?:string}).package??(item as {name?:string}).name??"")).filter(Boolean):[];
    useEffect(()=>()=>{if(preview)URL.revokeObjectURL(preview.url);},[preview]);
    async function showImage(op:Operation) {setImageError("");try{const blob=await protectedImage(`/api/v1/operations/${encodeURIComponent(op.id)}/screenshot`);setPreview({url:URL.createObjectURL(blob),id:op.id});}catch(error){setImageError(error instanceof Error?error.message:"Screenshot unavailable");}}
    function actionButton(action:string,label:string,sensitive=false) {return <button type="button" key={action} disabled={!online||busy||!allowed(action)} onClick={()=>sensitive?setConfirm({action}):mutation.mutate({action})}>{label}</button>;}
    return <section className="panel device-control"><h2>Device Control</h2><p className="muted">Actions run asynchronously. Results are confirmed by the manager. Android may restrict supported actions. Sleep / lock follows Android lock timeout and keyguard policy; secure locking is not guaranteed.</p>
        {!auth.identity && <p role="status">Authorize with a viewer, operator or administrator credential to access device controls.</p>}
        {!online&&<p className="error">Device offline. Controls are unavailable.</p>}
        <div className="actions control-toolbar">{[["state","Inspect state"],["properties","Device properties"],["screen.wake","Wake screen"],["screen.lock","Sleep / lock screen"],["screenshot","Capture screenshot"]].map(([action,label])=>actionButton(action,label))}{[["reboot","Reboot"],["reboot.recovery","Reboot to recovery"],["reboot.bootloader","Reboot to bootloader"]].map(([action,label])=>actionButton(action,label,true))}</div>
        {(mutation.error||upload.error)&&<p className="error" role="alert">{(mutation.error??upload.error)?.message}</p>}
        <h3>Installed applications</h3><div className="actions">{actionButton("apps.list","Refresh applications")}<label>Search applications<input value={search} onChange={e=>setSearch(e.target.value)} type="search"/></label></div>
        <div className="table-scroll"><table><thead><tr><th>Package</th><th>Actions</th></tr></thead><tbody>{packages.filter(pkg=>pkg.toLowerCase().includes(search.toLowerCase())).map(pkg=><tr key={pkg}><td className="mono">{pkg}</td><td><div className="actions">{[["apps.inspect","Inspect"],["apps.launch","Launch"],["apps.stop","Force-stop"],["apps.uninstall","Uninstall"]].map(([action,label])=><button key={action} disabled={!online||busy||!allowed(action)} onClick={()=>["apps.stop","apps.uninstall"].includes(action)?setConfirm({action,package:pkg}):mutation.mutate({action,package:pkg})}>{label}</button>)}</div></td></tr>)}</tbody></table></div>{!packages.length&&<p className="muted">Refresh applications to retrieve the installed package list.</p>}
        <label>Install APK (default maximum 64 MiB; server configuration may differ)<input type="file" accept=".apk,application/vnd.android.package-archive" disabled={!online||busy||!allowed("apps.install")} onChange={e=>{const file=e.target.files?.[0];if(file){if(file.size>64*1024*1024||!file.name.toLowerCase().endsWith(".apk")){setImageError("Choose an APK file no larger than the default 64 MiB upload limit. The server may enforce a smaller configured limit.");}else{setImageError("");upload.mutate(file);}}e.target.value="";}}/></label>{upload.isPending&&<p role="status">Uploading APK for validation and queued installation…</p>}
        <h3>Recent device operations</h3>{operations.error&&<p role="alert" className="error">{operations.error.message}</p>}{operations.data?.items.map(op=><article key={op.id} className="control-operation"><strong>{op.action}</strong> <span className="badge">{op.state}</span> <span className="muted">{op.duration===null?"":`${op.duration.toFixed(2)}s`}</span>{op.error&&<p role="alert" className="error">{op.error}</p>}{op.result&&op.action!=="apps.list"&&<pre>{JSON.stringify(op.result,null,2)}</pre>}{op.action==="screenshot"&&op.state==="succeeded"&&<button disabled={!allowed("screenshot")} onClick={()=>void showImage(op)}>Preview screenshot</button>}</article>)}
        {imageError&&<p className="error" role="alert">{imageError}</p>}{preview&&<div><img className="capture-preview" src={preview.url} alt="Captured device screen"/><div className="actions"><a className="button" href={preview.url} download={`screenshot-${preview.id}.png`}>Download screenshot</a><button onClick={()=>setPreview(null)}>Close preview</button></div></div>}
        {confirm&&<Confirmation title={`Confirm ${confirm.action}`} onCancel={()=>setConfirm(null)}><p>This action affects {confirm.package??"the device"}. Reboot modes depend on device support and may interrupt connectivity.</p><div className="actions"><button autoFocus onClick={()=>setConfirm(null)}>Cancel</button><button onClick={()=>{mutation.mutate({...confirm,confirmed:true});setConfirm(null);}}>Confirm action</button></div></Confirmation>}
    </section>;
}
