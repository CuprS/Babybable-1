import { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, FlatList, TextInput, Pressable, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { apiFetch } from "@/src/api";
import { useAuth } from "@/src/auth";
import { theme } from "@/src/theme";
import { track } from "@/src/analytics";

interface Msg { id: string; from_user_id: string; to_user_id: string; text: string; created_at: string }

export default function Chat() {
  const { userId, name } = useLocalSearchParams<{ userId: string; name?: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const listRef = useRef<FlatList>(null);

  const load = useCallback(async () => {
    if (!userId) return;
    try {
      const data = await apiFetch<Msg[]>(`/messages/thread/${userId}`);
      setMsgs(data);
    } catch {}
  }, [userId]);

  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t); }, [load]);

  const send = async () => {
    const t = text.trim();
    if (!t || !userId) return;
    setText("");
    try {
      const m = await apiFetch<Msg>("/messages", { method: "POST", body: JSON.stringify({ to_user_id: userId, text: t }) });
      track("chat_sent", { conversation_id: userId, message_type: "text", source: "client" });
      setMsgs((prev) => [...prev, m]);
      setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 50);
    } catch (e) {
      setText(t);
    }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="chat-back">
          <Feather name="arrow-left" size={24} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.name}>{name || "Chat"}</Text>
        <View style={{ width: 24 }} />
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }} keyboardVerticalOffset={80}>
        <FlatList
          ref={listRef}
          testID="chat-messages"
          data={msgs}
          keyExtractor={(m) => m.id}
          contentContainerStyle={{ padding: theme.space.lg, gap: theme.space.sm, paddingBottom: theme.space.lg }}
          onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: false })}
          renderItem={({ item }) => {
            const mine = item.from_user_id === user?.id;
            return (
              <View style={[styles.bubble, mine ? styles.mine : styles.theirs]}>
                <Text style={{ color: mine ? "#fff" : theme.color.onSurface, fontSize: theme.font.lg }}>{item.text}</Text>
              </View>
            );
          }}
          ListEmptyComponent={<Text style={{ color: theme.color.muted, textAlign: "center", marginTop: theme.space["3xl"] }}>Say hi 👋</Text>}
        />
        <View style={styles.inputRow}>
          <TextInput
            testID="chat-input"
            value={text}
            onChangeText={setText}
            placeholder="Type a message"
            placeholderTextColor={theme.color.muted}
            style={styles.input}
            multiline
          />
          <Pressable onPress={send} style={styles.send} testID="chat-send">
            <Feather name="send" size={18} color="#fff" />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  name: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface },
  bubble: { maxWidth: "78%", paddingHorizontal: theme.space.md, paddingVertical: 10, borderRadius: 18 },
  mine: { alignSelf: "flex-end", backgroundColor: theme.color.brand, borderBottomRightRadius: 4 },
  theirs: { alignSelf: "flex-start", backgroundColor: theme.color.surfaceSecondary, borderBottomLeftRadius: 4 },
  inputRow: { flexDirection: "row", alignItems: "flex-end", padding: theme.space.md, gap: theme.space.sm, borderTopColor: theme.color.border, borderTopWidth: StyleSheet.hairlineWidth, backgroundColor: theme.color.surface },
  input: { flex: 1, minHeight: 40, maxHeight: 120, paddingHorizontal: theme.space.md, paddingVertical: 10, borderRadius: 20, backgroundColor: theme.color.surfaceSecondary, color: theme.color.onSurface, fontSize: theme.font.lg },
  send: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
});
