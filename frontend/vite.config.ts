import { defineConfig } from "vitest/config";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
export default defineConfig({
    plugins: [react(), tailwindcss()],
    resolve: {
        alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
    server: { proxy: { "/api": "http://127.0.0.1:9000" } },
    test: {
        environment: "jsdom",
        setupFiles: ["./src/test-setup.ts"],
        css: true,
    },
});
