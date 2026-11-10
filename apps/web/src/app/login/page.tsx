import { AuthForm } from "@/components/auth-form";
import { AuthScreen } from "@/components/auth-screen";

export default function LoginPage() {
  return (
    <AuthScreen
      title="Sign in"
      description="Sessions stay on the server. The browser only holds an HttpOnly cookie."
    >
      <AuthForm mode="login" />
    </AuthScreen>
  );
}
