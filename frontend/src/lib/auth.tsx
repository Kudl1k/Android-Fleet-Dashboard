import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AUTH_EXPIRED_EVENT, getControlToken, request, setControlToken } from "./api";
export interface Identity { identity: string; role: string; permissions: string[] }
const AuthContext = createContext({ token: "", identity: undefined as Identity | undefined, error: "", can: (_permission: string): boolean => { void _permission; return false; }, setToken: (_token: string) => { void _token; } });
export function AuthProvider({ children }: { children: ReactNode }) {
    const [token, update] = useState(getControlToken);
    const client = useQueryClient();
    useEffect(() => {
        const expired = () => { update(""); client.clear(); };
        window.addEventListener(AUTH_EXPIRED_EVENT, expired);
        return () => window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
    }, [client]);
    const identity = useQuery({queryKey:["identity",token], queryFn:()=>request<Identity>("/api/v1/auth/me"), retry:false});
    return <AuthContext.Provider value={{token, identity:identity.data, error:identity.error?.message ?? "", can:(permission)=>identity.data?.permissions.includes(permission) ?? false, setToken:(value)=>{setControlToken(value); update(value); client.clear();}}}>{children}</AuthContext.Provider>;
}
export function useAuth() { return useContext(AuthContext); }
