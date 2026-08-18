import { Routes, Route, Navigate } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { CommandCenter } from "@/features/command-center/CommandCenter";
import { ResearchBoard } from "@/features/research/ResearchBoard";
import { MyTrip } from "@/features/trip/MyTrip";
import { AgentControl } from "@/features/agent-control/AgentControl";
import { EngineSettings } from "@/features/engine/EngineSettings";
import { Profile } from "@/features/profile/Profile";

export function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<CommandCenter />} />
        <Route path="/research" element={<ResearchBoard />} />
        <Route path="/trip" element={<MyTrip />} />
        <Route path="/agents" element={<AgentControl />} />
        <Route path="/engine" element={<EngineSettings />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
