import { Redirect } from "expo-router";
import { useAuth } from "@/src/auth";
import { View, ActivityIndicator } from "react-native";
import { theme } from "@/src/theme";

export default function Index() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface }}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }
  return <Redirect href={user ? "/(tabs)" : "/onboarding"} />;
}
