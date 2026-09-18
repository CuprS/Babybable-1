import React, { createContext, useCallback, useContext, useState } from "react";
import { View, Text, StyleSheet, Modal, Pressable, TextInput, Animated } from "react-native";
import { Feather } from "@expo/vector-icons";
import { theme } from "./theme";
import { apiFetch } from "./api";
import { useToast } from "./toast";
import { track } from "./analytics";

export interface ReviewPromptPayload {
  bookingId?: string;
  tutorId: string;
  tutorName: string;
}

interface Ctx {
  openReview: (p: ReviewPromptPayload) => void;
}

const ReviewCtx = createContext<Ctx | undefined>(undefined);

export function ReviewPromptProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [payload, setPayload] = useState<ReviewPromptPayload | null>(null);

  const openReview = useCallback((p: ReviewPromptPayload) => {
    setPayload(p);
    setOpen(true);
  }, []);

  const close = () => { setOpen(false); setPayload(null); };

  return (
    <ReviewCtx.Provider value={{ openReview }}>
      {children}
      <ReviewSheet open={open} onClose={close} payload={payload} />
    </ReviewCtx.Provider>
  );
}

export function useReviewPrompt(): Ctx {
  const v = useContext(ReviewCtx);
  if (!v) throw new Error("useReviewPrompt outside ReviewPromptProvider");
  return v;
}

function ReviewSheet({ open, onClose, payload }: { open: boolean; onClose: () => void; payload: ReviewPromptPayload | null }) {
  const [rating, setRating] = useState<number>(0);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const { show } = useToast();

  React.useEffect(() => {
    if (open) { setRating(0); setComment(""); }
  }, [open]);

  const submit = async () => {
    if (!payload || rating < 1) return;
    setSubmitting(true);
    try {
      await apiFetch("/reviews", {
        method: "POST",
        body: JSON.stringify({
          tutor_id: payload.tutorId,
          booking_id: payload.bookingId,
          rating,
          comment: comment.trim(),
        }),
      });
      track("review_submitted", { tutor_id: payload.tutorId, rating, has_comment: comment.trim().length > 0 });
      show({ kind: "success", title: "Thanks for the feedback!", body: `Your ${rating}★ review is live.` });
      onClose();
    } catch (e: any) {
      show({ kind: "error", title: "Couldn't save review", body: e?.message || "Try again in a moment." });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal visible={open} transparent animationType="slide" onRequestClose={onClose}>
      <View style={sheetStyles.backdrop}>
        <View style={sheetStyles.sheet} testID="review-sheet">
          <View style={sheetStyles.grabber} />
          <View style={sheetStyles.header}>
            <View style={{ flex: 1 }}>
              <Text style={sheetStyles.title}>Rate your session</Text>
              {payload?.tutorName ? (
                <Text style={sheetStyles.sub}>How did it go with {payload.tutorName}?</Text>
              ) : null}
            </View>
            <Pressable onPress={onClose} hitSlop={12} testID="review-close">
              <Feather name="x" size={22} color={theme.color.onSurface} />
            </Pressable>
          </View>

          <View style={sheetStyles.starRow}>
            {[1, 2, 3, 4, 5].map((n) => {
              const filled = n <= rating;
              return (
                <StarButton key={n} n={n} filled={filled} onPress={() => setRating(n)} />
              );
            })}
          </View>
          {rating > 0 && (
            <Text style={sheetStyles.ratingLabel}>{RATING_LABELS[rating - 1]}</Text>
          )}

          <TextInput
            testID="review-comment"
            value={comment}
            onChangeText={setComment}
            placeholder="Share what you loved (or what could be better)…"
            placeholderTextColor={theme.color.muted}
            multiline
            style={sheetStyles.input}
          />

          <Pressable
            testID="review-submit"
            onPress={submit}
            disabled={submitting || rating < 1}
            style={[sheetStyles.submit, (submitting || rating < 1) && sheetStyles.submitDisabled]}
          >
            <Text style={sheetStyles.submitText}>
              {submitting ? "Saving…" : rating < 1 ? "Pick a rating" : "Post review"}
            </Text>
          </Pressable>

          <Text style={sheetStyles.foot}>Your review helps other families choose a great tutor.</Text>
        </View>
      </View>
    </Modal>
  );
}

const RATING_LABELS = ["Not for us", "Could be better", "Good", "Great!", "Loved it 💫"];

function StarButton({ n, filled, onPress }: { n: number; filled: boolean; onPress: () => void }) {
  const scale = React.useRef(new Animated.Value(1)).current;
  const handle = () => {
    Animated.sequence([
      Animated.timing(scale, { toValue: 1.25, duration: 120, useNativeDriver: true }),
      Animated.timing(scale, { toValue: 1, duration: 120, useNativeDriver: true }),
    ]).start();
    onPress();
  };
  return (
    <Pressable onPress={handle} hitSlop={8} testID={`review-star-${n}`}>
      <Animated.View style={{ transform: [{ scale }] }}>
        <Feather
          name="star"
          size={38}
          color={filled ? theme.color.brand : theme.color.borderStrong}
          style={filled ? { textShadowColor: theme.color.brand, textShadowRadius: 4 } : undefined}
        />
      </Animated.View>
    </Pressable>
  );
}

const sheetStyles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(44,36,33,0.55)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingBottom: theme.space["3xl"],
  },
  grabber: { alignSelf: "center", width: 44, height: 4, borderRadius: 2, backgroundColor: theme.color.borderStrong, marginTop: 10 },
  header: { flexDirection: "row", alignItems: "flex-start", padding: theme.space.lg, paddingBottom: theme.space.sm, gap: theme.space.md },
  title: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface },
  sub: { color: theme.color.onSurfaceSecondary, marginTop: 2 },
  starRow: {
    flexDirection: "row",
    justifyContent: "center",
    gap: theme.space.md,
    marginTop: theme.space.md,
    paddingVertical: theme.space.md,
  },
  ratingLabel: {
    textAlign: "center",
    color: theme.color.brandDark,
    fontWeight: "700",
    fontSize: theme.font.lg,
    marginBottom: theme.space.sm,
  },
  input: {
    marginHorizontal: theme.space.lg,
    marginTop: theme.space.md,
    minHeight: 96,
    borderWidth: 1,
    borderColor: theme.color.border,
    borderRadius: theme.radius.md,
    padding: theme.space.md,
    color: theme.color.onSurface,
    textAlignVertical: "top",
    backgroundColor: theme.color.surfaceSecondary,
  },
  submit: {
    marginHorizontal: theme.space.lg,
    marginTop: theme.space.lg,
    height: 52,
    borderRadius: theme.radius.pill,
    backgroundColor: theme.color.brand,
    alignItems: "center",
    justifyContent: "center",
  },
  submitDisabled: { opacity: 0.5 },
  submitText: { color: "#fff", fontWeight: "700", fontSize: theme.font.lg },
  foot: {
    color: theme.color.muted,
    fontSize: theme.font.sm,
    textAlign: "center",
    marginTop: theme.space.md,
    paddingHorizontal: theme.space.lg,
  },
});
