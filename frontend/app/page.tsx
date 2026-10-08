import AuthGate from "@/components/AuthGate";
import JarvisOrb from "@/components/JarvisOrb";

export default function Home() {
  return (
    <AuthGate>
      <JarvisOrb />
    </AuthGate>
  );
}
