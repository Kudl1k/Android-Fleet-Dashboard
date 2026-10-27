import { describe, expect, it } from "vitest";
import {
    formatDuration,
    parseRunOutput,
    phaseLabel,
    runPhase,
} from "./runOutput";

const report = [
    "MiB hashed 34786 MiB/s 869.6",
    '\tCommand being timed: "sh -c python3 bench.py"',
    "\tUser time (seconds): 39.77",
    "\tSystem time (seconds): 0.12",
    "\tPercent of CPU this job got: 99%",
    "\tElapsed (wall clock) time (h:mm:ss or m:ss): 0:40.27",
    "\tMaximum resident set size (kbytes): 76580",
    "\tExit status: 0",
    "",
].join("\n");

describe("run output", () => {
    it("separates program output from the GNU time report", () => {
        const { program, stats } = parseRunOutput(report);
        expect(program).toBe("MiB hashed 34786 MiB/s 869.6");
        expect(stats).toEqual({
            elapsedSeconds: 40.27,
            cpuPercent: 99,
            userSeconds: 39.77,
            systemSeconds: 0.12,
            maxRssBytes: 76580 * 1024,
            exitStatus: 0,
        });
    });
    it("reads hour clocks and keeps output without a report", () => {
        const long = report.replace("0:40.27", "1:02:03");
        expect(parseRunOutput(long).stats?.elapsedSeconds).toBe(3723);
        expect(parseRunOutput("still running\n")).toEqual({
            program: "still running\n",
            stats: null,
        });
        expect(parseRunOutput(null).stats).toBeNull();
    });
    it("derives the phase from the session and the exit status", () => {
        expect(runPhase({ state: "active" })).toBe("running");
        expect(runPhase({ state: "closed", output: report })).toBe("succeeded");
        const failed = {
            state: "closed",
            output: report.replace("Exit status: 0", "Exit status: 2"),
        };
        expect(runPhase(failed)).toBe("failed");
        expect(phaseLabel(failed)).toBe("Failed (exit 2)");
        expect(phaseLabel({ state: "closed", output: "" })).toBe("Stopped");
        expect(phaseLabel({ state: "timed_out" })).toBe("Timed out");
    });
    it("formats durations for people", () => {
        expect(formatDuration(0.6)).toBe("0.6 s");
        expect(formatDuration(55)).toBe("55 s");
        expect(formatDuration(287)).toBe("4 min 47 s");
        expect(formatDuration(3723)).toBe("1 h 2 min");
    });
});
