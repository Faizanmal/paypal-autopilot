import { AuthForm } from "@/components/auth-form";
import { AuthScreen } from "@/components/auth-screen";

export default function RegisterPage() {
  return (
    <AuthScreen
      title="Create a workspace"
      description="You become the owner. Payout approval stays on for every workspace."
    >
      <AuthForm mode="register" />
    </AuthScreen>
  );
}
