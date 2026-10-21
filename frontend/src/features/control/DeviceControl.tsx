import ListRegion from "../../components/ListRegion";
import StateBadge from "../../components/StateBadge";
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
    const filteredPackages = packages.filter(pkg=>pkg.toLowerCase().includes(search.toLowerCase()));
    useEffect(()=>()=>{if(preview)URL.revokeObjectURL(preview.url);},[preview]);
    async function showImage(op:Operation) {setImageError("");try{const blob=await protectedImage(`/api/v1/operations/${encodeURIComponent(op.id)}/screenshot`);setPreview({url:URL.createObjectURL(blob),id:op.id});}catch(error){setImageError(error instanceof Error?error.message:"Screenshot unavailable");}}
    function actionButton(action:string,label:string,sensitive=false) {return <button type="button" className={sensitive?"danger":undefined} aria-busy={mutation.isPending&&mutation.variables?.action===action} key={action} disabled={!online||busy||!allowed(action)} onClick={()=>sensitive?setConfirm({action}):mutation.mutate({action})}>{label}</button>;}
    return <section className="panel device-control"><h2>Device controls</h2><p className="muted">Actions run asynchronously. Results are confirmed by the manager. Android may restrict supported actions. Sleep / lock follows Android lock timeout and keyguard policy; secure locking is not guaranteed.</p>
        {!auth.identity && <p role="status">Authorize with a viewer, operator or administrator credential to access device controls.</p>}
        {!online&&<p className="error">Device offline. Controls are unavailable.</p>}
        <div className="device-control-groups">
            <fieldset className="device-action-group"><legend>Inspect device</legend><div className="actions device-actions">{[["state","Inspect state"],["properties","Device properties"],["screenshot","Capture screenshot"]].map(([action,label])=>actionButton(action,label))}</div></fieldset>
            <fieldset className="device-action-group"><legend>Screen power</legend><div className="actions device-actions">{[["screen.wake","Wake screen"],["screen.lock","Sleep / lock screen"]].map(([action,label])=>actionButton(action,label))}</div></fieldset>
        </div>
        <fieldset className="device-action-group device-danger-zone"><legend>Restart device</legend><p className="muted">These actions interrupt device connectivity and require confirmation.</p><div className="actions device-actions">{[["reboot","Reboot"],["reboot.recovery","Reboot to recovery"],["reboot.bootloader","Reboot to bootloader"]].map(([action,label])=>actionButton(action,label,true))}</div></fieldset>
        {mutation.isPending&&<p role="status">Requesting device action…</p>}
        {(mutation.error||upload.error)&&<p className="error" role="alert">{(mutation.error??upload.error)?.message}</p>}
        <div className="device-list-heading"><h3>Installed applications</h3><span className="muted">{filteredPackages.length} of {packages.length} loaded</span></div><div className="actions device-actions device-form-row"><label>Search applications<input value={search} onChange={e=>setSearch(e.target.value)} type="search"/></label>{actionButton("apps.list","Refresh applications")}</div>
        <ListRegion label="Installed applications" className="device-applications"><table><thead><tr><th scope="col">Package</th><th scope="col">Actions</th></tr></thead><tbody>{filteredPackages.map(pkg=><tr key={pkg}><td><span className="device-cell-label" aria-hidden="true">Package</span><span className="mono">{pkg}</span></td><td><span className="device-cell-label" aria-hidden="true">Actions</span><div className="actions device-actions device-package-actions"><div className="device-package-group" role="group" aria-label={`Inspect or launch ${pkg}`}>{[["apps.inspect","Inspect"],["apps.launch","Launch"]].map(([action,label])=><button key={action} disabled={!online||busy||!allowed(action)} onClick={()=>mutation.mutate({action,package:pkg})}>{label}</button>)}</div><div className="device-package-group device-package-danger" role="group" aria-label={`Stop or uninstall ${pkg}`}>{[["apps.stop","Force-stop"],["apps.uninstall","Uninstall"]].map(([action,label])=><button className="danger" key={action} disabled={!online||busy||!allowed(action)} onClick={()=>setConfirm({action,package:pkg})}>{label}</button>)}</div></div></td></tr>)}</tbody></table>{filteredPackages.length === 0 && <p className="muted list-empty">{packages.length ? "No applications match this search." : list ? "No application records returned." : "Refresh applications to retrieve the installed package list."}</p>}</ListRegion>
        <div className="device-upload"><label>Install APK (default maximum 64 MiB; server configuration may differ)<input type="file" accept=".apk,application/vnd.android.package-archive" disabled={!online||busy||!allowed("apps.install")} onChange={e=>{const file=e.target.files?.[0];if(file){if(file.size>64*1024*1024||!file.name.toLowerCase().endsWith(".apk")){setImageError("Choose an APK file no larger than the default 64 MiB upload limit. The server may enforce a smaller configured limit.");}else{setImageError("");upload.mutate(file);}}e.target.value="";}}/></label>{upload.isPending&&<p role="status">Uploading APK for validation and queued installation…</p>}</div>
        <div className="device-list-heading"><h3>Recent device operations</h3><span className="muted">{operations.data?.items.length ?? 0} loaded</span></div>
        {operations.error&&<p role="alert" className="error">{operations.error.message}</p>}
        <div className="device-operation-columns" aria-hidden="true"><span>Operation</span><span>Status</span><span>Duration</span><span>Actions</span></div><ListRegion label="Recent device operations"><ul className="device-operation-list">{operations.data?.items.map(op=><li key={op.id} className="control-operation">
            <div className="device-operation-row"><strong>{op.action}</strong><StateBadge state={op.state} /><span className={`device-operation-duration ${op.duration == null ? "muted" : ""}`}><span className="sr-only">Duration: </span>{op.duration == null ? "Unavailable" : `${op.duration.toFixed(2)} s`}</span><div className="device-operation-actions">{op.action==="screenshot"&&op.state==="succeeded"&&<button disabled={!allowed("screenshot")} onClick={()=>void showImage(op)}>Preview screenshot</button>}</div></div>
            {op.error&&<p role="alert" className="error">{op.error}</p>}
            {op.result&&op.action!=="apps.list"&&<details className="device-operation-result"><summary>View operation result</summary><pre>{JSON.stringify(op.result,null,2)}</pre></details>}
        </li>)}</ul>{!operations.isPending && !operations.isError && !operations.data?.items.length && <p className="muted list-empty">No recent device operations.</p>}{operations.isPending && auth.can("operations.read") && <p role="status">Loading recent operations…</p>}{!auth.can("operations.read") && <p className="muted list-empty">Operation history permission is required.</p>}</ListRegion>
        {imageError&&<p className="error" role="alert">{imageError}</p>}{preview&&<div><img className="capture-preview" src={preview.url} alt="Captured device screen"/><div className="actions device-actions"><a className="button primary" href={preview.url} download={`screenshot-${preview.id}.png`}>Download screenshot</a><button onClick={()=>setPreview(null)}>Close preview</button></div></div>}
        {confirm&&<Confirmation title={`Confirm ${confirm.action}`} onCancel={()=>setConfirm(null)}><p>This action affects {confirm.package??"the device"}. Reboot modes depend on device support and may interrupt connectivity.</p><div className="actions device-dialog-actions"><button autoFocus onClick={()=>setConfirm(null)}>Cancel</button><button className="danger" onClick={()=>{mutation.mutate({...confirm,confirmed:true});setConfirm(null);}}>Confirm action</button></div></Confirmation>}
    </section>;
}
