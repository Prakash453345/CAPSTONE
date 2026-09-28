import { beforeEach, describe, expect, it } from "vitest";
import { useNotificationStore } from "@/store/notificationStore";
import type { NotificationEvent } from "@/types";

function ev(over: Partial<NotificationEvent> = {}): NotificationEvent {
  return {
    id: `n-${Math.random()}`,
    kind: "anomaly-created",
    tone: "warn",
    title: "t",
    message: "m",
    atMs: Date.now(),
    ...over,
  };
}

function reset() {
  useNotificationStore.setState({ items: [], unreadCount: 0 });
}

describe("notificationStore", () => {
  beforeEach(reset);

  it("push prepends new events and grows unreadCount", () => {
    useNotificationStore.getState().push([ev({ id: "a" })]);
    useNotificationStore.getState().push([ev({ id: "b" }), ev({ id: "c" })]);
    const s = useNotificationStore.getState();
    expect(s.items.map((i) => i.id)).toEqual(["b", "c", "a"]);
    expect(s.unreadCount).toBe(3);
  });

  it("push with an empty array is a no-op", () => {
    useNotificationStore.getState().push([ev({ id: "a" })]);
    useNotificationStore.getState().push([]);
    expect(useNotificationStore.getState().items.length).toBe(1);
    expect(useNotificationStore.getState().unreadCount).toBe(1);
  });

  it("markAllRead clears unreadCount but keeps history", () => {
    useNotificationStore.getState().push([ev({ id: "a" })]);
    useNotificationStore.getState().markAllRead();
    expect(useNotificationStore.getState().unreadCount).toBe(0);
    expect(useNotificationStore.getState().items.length).toBe(1);
  });

  it("dismiss removes a single item", () => {
    useNotificationStore.getState().push([ev({ id: "a" }), ev({ id: "b" })]);
    useNotificationStore.getState().dismiss("a");
    expect(useNotificationStore.getState().items.map((i) => i.id)).toEqual(["b"]);
  });

  it("clear empties both items and unreadCount", () => {
    useNotificationStore.getState().push([ev({ id: "a" })]);
    useNotificationStore.getState().clear();
    expect(useNotificationStore.getState()).toMatchObject({ items: [], unreadCount: 0 });
  });

  it("caps history at 40 items", () => {
    const many = Array.from({ length: 45 }, (_, i) => ev({ id: `e${i}` }));
    useNotificationStore.getState().push(many);
    expect(useNotificationStore.getState().items.length).toBe(40);
  });
});
