"use client";

import Image from "next/image";
import Link from "next/link";
import React, { useEffect, useRef, useState } from "react";
import {
  IconClock,
  IconMapPin,
  IconCloudRain,
  IconAlertTriangle,
  IconShield,
  IconPaperclip,
  IconSend,
  IconChatBubble,
  IconRoute,
  IconUser,
} from "@/components/ui/icons";
import type { components } from "@/lib/api/generated/public-api";
import { api } from "@/lib/api/client";
import { createRequestId } from "@/lib/api/id";

type Schema = components["schemas"];

interface Message {
  id: string;
  sender: "user" | "assistant";
  text: string;
  recommendation?: Schema["RecommendationResponse"];
  timestamp: string;
  isPlan?: boolean;
}

const QUICK_PROMPTS = [
  {
    label: "ตรวจสอบเส้นทาง",
    query: "ช่วยตรวจสอบเส้นทางและความปลอดภัยของทริปของฉันให้หน่อย มีจุดเสี่ยงหรือข้อควรระวังอะไรบ้างไหม?",
    icon: "route",
  },
  {
    label: "พยากรณ์อากาศ",
    query: "สภาพอากาศตลอดแนวเส้นทางและจุดหมายปลายทางเป็นอย่างไรบ้าง มีฝนตกหรือความเสี่ยงสภาพอากาศไหม?",
    icon: "weather",
  },
  {
    label: "ความช่วยเหลือฉุกเฉิน",
    query: "หากเกิดเหตุฉุกเฉิน อุบัติเหตุ น้ำท่วม หรือถนนปิดในเส้นทาง มีเบอร์ติดต่อและขั้นตอนรับมืออย่างไรบ้าง?",
    icon: "emergency",
  },
];

function FormattedMessageText({ text }: { text: string }) {
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];

  let currentList: string[] = [];
  let isNumbered = false;

  const flushList = () => {
    if (currentList.length > 0) {
      if (isNumbered) {
        elements.push(
          <ol key={`ol-${elements.length}`} className="my-1.5 ml-5 list-decimal space-y-1">
            {currentList.map((item, idx) => (
              <li key={idx} className="leading-relaxed">
                {renderInline(item)}
              </li>
            ))}
          </ol>,
        );
      } else {
        elements.push(
          <ul key={`ul-${elements.length}`} className="my-1.5 ml-5 list-disc space-y-1">
            {currentList.map((item, idx) => (
              <li key={idx} className="leading-relaxed">
                {renderInline(item)}
              </li>
            ))}
          </ul>,
        );
      }
      currentList = [];
      isNumbered = false;
    }
  };

  const renderInline = (str: string): React.ReactNode => {
    const parts = str.split(/(\*\*.*?\*\*|\*.*?\*|`.*?`)/g);
    return parts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return (
          <strong key={i} className="font-semibold text-slate-900 dark:text-slate-50">
            {part.slice(2, -2)}
          </strong>
        );
      }
      if (part.startsWith("*") && part.endsWith("*")) {
        return <em key={i}>{part.slice(1, -1)}</em>;
      }
      if (part.startsWith("`") && part.endsWith("`")) {
        return (
          <code
            key={i}
            className="px-1.5 py-0.5 bg-emerald-50 text-emerald-800 rounded text-xs font-mono"
          >
            {part.slice(1, -1)}
          </code>
        );
      }
      return part;
    });
  };

  lines.forEach((line, index) => {
    const trimmed = line.trim();

    if (!trimmed) {
      flushList();
      elements.push(<div key={`spacer-${index}`} className="h-1.5" />);
      return;
    }

    if (trimmed.startsWith("### ")) {
      flushList();
      elements.push(
        <h4
          key={`h4-${index}`}
          className="font-bold text-sm text-emerald-950 dark:text-emerald-100 mt-2 mb-1"
        >
          {renderInline(trimmed.slice(4))}
        </h4>,
      );
      return;
    }

    if (trimmed.startsWith("## ")) {
      flushList();
      elements.push(
        <h3
          key={`h3-${index}`}
          className="font-bold text-base text-emerald-950 dark:text-emerald-100 mt-2.5 mb-1"
        >
          {renderInline(trimmed.slice(3))}
        </h3>
      );
      return;
    }

    if (trimmed.startsWith("---") || trimmed.startsWith("***")) {
      flushList();
      elements.push(<hr key={`hr-${index}`} className="my-2 border-slate-200" />);
      return;
    }

    const numMatch = trimmed.match(/^\d+\.\s+(.*)/);
    if (numMatch) {
      if (!isNumbered && currentList.length > 0) flushList();
      isNumbered = true;
      currentList.push(numMatch[1]);
      return;
    }

    const bulletMatch = trimmed.match(/^[-*•]\s+(.*)/);
    if (bulletMatch) {
      if (isNumbered && currentList.length > 0) flushList();
      isNumbered = false;
      currentList.push(bulletMatch[1]);
      return;
    }

    flushList();
    elements.push(
      <p key={`p-${index}`} className="mb-1 leading-relaxed">
        {renderInline(line)}
      </p>,
    );
  });

  flushList();

  return <div className="formatted-chat-text">{elements}</div>;
}

export function AssistantView({ conversationId }: { conversationId?: string }) {
  const [activeConvId, setActiveConvId] = useState<string>(
    conversationId && conversationId !== "new" ? conversationId : createRequestId(),
  );
  const [conversations, setConversations] = useState<
    Array<{ conversation_id: string; title: string; updated_at: string }>
  >([]);
  const [activeTrip, setActiveTrip] = useState<Schema["Trip"] | null>(null);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome-init",
      sender: "assistant",
      text: "สวัสดีครับ! ผมคือ **Smart Travel Assistant** ผู้ช่วยการเดินทาง AI ของคุณ\n\nพร้อมช่วยตอบทุกข้อสงสัยเกี่ยวกับการเดินทาง แนะนำสถานที่ท่องเที่ยว เช็กสภาพอากาศ หรือประเมินความปลอดภัยตลอดเส้นทางครับ สอบถามเรื่องใดพิมพ์มาได้เลยครับ! 🌟",
      timestamp: new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      }),
    },
  ]);
  const [inputValue, setInputValue] = useState("");
  const [liveLocationEnabled, setLiveLocationEnabled] = useState(false);
  const [liveLocationCoords, setLiveLocationCoords] = useState<{
    lat: number;
    lng: number;
  } | null>(null);
  const [isSending, setIsSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isSending]);

  // Load conversations & active trip context
  useEffect(() => {
    const controller = new AbortController();

    async function loadInitialContext() {
      try {
        const promises: [Promise<any>, Promise<any>, Promise<any>?] = [
          api.GET("/api/v1/conversations", { signal: controller.signal }).catch(() => null),
          api.GET("/api/v1/trips", {
            params: { query: { limit: 1 } },
            signal: controller.signal,
          }).catch(() => null),
        ];

        if (activeConvId && activeConvId !== "new") {
          promises.push(
            (api.GET as any)(
              "/api/v1/conversations/{conversation_id}/messages",
              {
                params: { path: { conversation_id: activeConvId } },
                signal: controller.signal,
              },
            ).catch(() =>
              (api.GET as any)(
                "/api/v1/conversations/{id}/messages",
                {
                  params: { path: { id: activeConvId } },
                  signal: controller.signal,
                },
              ).catch(() => null),
            ),
          );
        }

        const [convsRes, tripsRes, msgsRes] = await Promise.all(promises);

        if (convsRes?.data?.data && convsRes.data.data.length > 0) {
          setConversations(
            convsRes.data.data.map((c: any) => ({
              conversation_id: c.conversation_id,
              title: c.title || "คำถามความปลอดภัยการเดินทาง",
              updated_at: new Date(c.updated_at).toLocaleDateString("th-TH"),
            })),
          );
        }

        if (msgsRes?.data?.data && msgsRes.data.data.length > 0) {
          setMessages(
            msgsRes.data.data.map((m: any) => ({
              id: m.message_id || createRequestId(),
              sender: m.role?.toLowerCase() === "user" ? "user" : "assistant",
              text: m.content || "",
              timestamp: m.created_at
                ? new Date(m.created_at).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                : new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
            })),
          );
        }

        if (tripsRes?.data?.data && tripsRes.data.data.length > 0) {
          const tripDetail = await api.GET("/api/v1/trips/{trip_id}", {
            params: { path: { trip_id: tripsRes.data.data[0].trip_id } },
            signal: controller.signal,
          }).catch(() => null);

          if (tripDetail?.data?.data) {
            setActiveTrip(tripDetail.data.data);
          }
        }
      } catch {
        // Handled silently
      }
    }

    void loadInitialContext();

    return () => {
      controller.abort();
    };
  }, [activeConvId]);

  async function handleSendMessage(textToSend: string) {
    const text = textToSend.trim();
    if (!text || isSending) return;

    const userMsgId = createRequestId();
    const userMsg: Message = {
      id: userMsgId,
      sender: "user",
      text,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInputValue("");
    setIsSending(true);

    // Update conversation title in the sidebar if needed
    setConversations((prev) => {
      const exists = prev.some((c) => c.conversation_id === activeConvId);
      if (exists) return prev;
      return [
        {
          conversation_id: activeConvId,
          title: text.length > 25 ? text.slice(0, 25) + "…" : text,
          updated_at: new Date().toLocaleDateString("th-TH"),
        },
        ...prev,
      ];
    });

    try {
      // Build trip context if available
      const tripContext = activeTrip
        ? {
            trip_id: activeTrip.trip_id,
            title:
              activeTrip.title ||
              `${activeTrip.origin.display_name} → ${activeTrip.destination.display_name}`,
            origin: {
              display_name: activeTrip.origin.display_name,
              lat: activeTrip.origin.coordinates?.coordinates?.[1],
              lon: activeTrip.origin.coordinates?.coordinates?.[0],
            },
            destination: {
              display_name: activeTrip.destination.display_name,
              lat: activeTrip.destination.coordinates?.coordinates?.[1],
              lon: activeTrip.destination.coordinates?.coordinates?.[0],
            },
            departure_time: activeTrip.departure_time,
            arrival_time: activeTrip.return_time ?? undefined,
            travel_mode: activeTrip.travel_modes?.join(", ") || "ANY",
            status: activeTrip.status,
          }
        : null;

      // Format messages history for Gemini API
      const chatPayloadMessages = newMessages.map((m) => ({
        role: m.sender === "user" ? ("user" as const) : ("assistant" as const),
        content: m.text,
      }));

      const response = await fetch("/api/assistant/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          messages: chatPayloadMessages,
          tripContext,
          liveLocation: liveLocationEnabled && liveLocationCoords ? liveLocationCoords : null,
          locale: "th",
        }),
      });

      const data = await response.json();

      if (response.ok && data.reply) {
        const assistantMsg: Message = {
          id: createRequestId(),
          sender: "assistant",
          text: data.reply,
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } else {
        const fallbackMsg: Message = {
          id: createRequestId(),
          sender: "assistant",
          text:
            data?.error ||
            "ขออภัยครับ ระบบไม่สามารถรับข้อมูลจาก Gemini ได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง",
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        };
        setMessages((prev) => [...prev, fallbackMsg]);
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: createRequestId(),
          sender: "assistant",
          text: "เกิดข้อผิดพลาดในการเชื่อมต่อ กรุณาตรวจสอบอินเทอร์เน็ตหรือลองใหม่ภายหลังครับ",
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  async function toggleLiveLocation() {
    if (liveLocationEnabled) {
      setLiveLocationEnabled(false);
      setLiveLocationCoords(null);
    } else {
      if ("geolocation" in navigator) {
        navigator.geolocation.getCurrentPosition(
          (position) => {
            setLiveLocationCoords({
              lat: position.coords.latitude,
              lng: position.coords.longitude,
            });
            setLiveLocationEnabled(true);
          },
          () => {
            alert("การเข้าถึงตำแหน่งถูกปฏิเสธในการตั้งค่าเบราว์เซอร์");
          },
        );
      } else {
        setLiveLocationEnabled(true);
      }
    }
  }

  const targetTripId = activeTrip?.trip_id;

  return (
    <div className="assistant-page-container">
      {/* =======================================================================
          COLUMN 1: RECENT CHATS SIDEBAR
          ======================================================================= */}
      <aside className="assistant-sidebar-card" aria-label="ประวัติการสนทนา">
        <div className="assistant-sidebar-header">
          <IconClock width={18} height={18} className="sidebar-clock-icon" aria-hidden="true" />
          <h2 className="sidebar-heading">แชทล่าสุด (Recent chats)</h2>
        </div>

        <div className="recent-conversations-list">
          {conversations.map((c) => (
            <button
              key={c.conversation_id}
              type="button"
              className={`conv-item-btn ${c.conversation_id === activeConvId ? "active" : ""}`}
              onClick={() => {
                setActiveConvId(c.conversation_id);
              }}
            >
              <div className="conv-icon-wrap">
                <IconChatBubble width={16} height={16} />
              </div>
              <div className="conv-copy">
                <span className="conv-title">{c.title}</span>
                <span className="conv-date">{c.updated_at}</span>
              </div>
              <span className="conv-chevron" aria-hidden="true">
                ›
              </span>
            </button>
          ))}
        </div>

        <div className="assistant-sidebar-footer">
          <button
            type="button"
            className="new-chat-btn"
            onClick={() => {
              const newId = createRequestId();
              setActiveConvId(newId);
              setMessages([
                {
                  id: "welcome-new",
                  sender: "assistant",
                  text: "เริ่มการสนทนาใหม่แล้วครับ! มีเรื่องใดเกี่ยวกับการเดินทาง สถานที่ท่องเที่ยว หรือความปลอดภัยที่ต้องการให้ผมช่วยดูแลไหมครับ? 😊",
                  timestamp: new Date().toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  }),
                },
              ]);
            }}
          >
            <span className="new-chat-plus">＋</span> เริ่มแชทใหม่ (New chat)
          </button>
        </div>
      </aside>

      {/* =======================================================================
          COLUMN 2: CENTER TRAVEL ASSISTANT CHAT
          ======================================================================= */}
      <section className="assistant-main-card" aria-label="ห้องแชทผู้ช่วยการเดินทาง">
        {/* Header */}
        <header className="assistant-card-header">
          <div className="assistant-title-row">
            <h1 className="assistant-heading">ผู้ช่วยการเดินทาง (Travel Assistant)</h1>
            <span className="online-status-badge">
              <span className="online-dot" /> Gemini AI พร้อมตอบคำถาม
            </span>
          </div>
          <p className="assistant-subtitle">
            เพื่อนร่วมทาง AI อัจฉริยะ เพื่อการเดินทางที่ราบรื่น ปลอดภัย และอุ่นใจของคุณ
          </p>
        </header>

        {/* Message Transcript */}
        <div className="assistant-transcript" role="log" aria-live="polite">
          {messages.map((m) => (
            <div
              key={m.id}
              className={`chat-bubble-row ${m.sender === "user" ? "user-row" : "assistant-row"}`}
            >
              {m.sender === "assistant" && (
                <div className="assistant-avatar-badge" aria-hidden="true">
                  <Image
                    src="/assets/mascot/mascot-welcome.png"
                    width={40}
                    height={40}
                    alt="มาสคอตผู้ช่วยการเดินทาง"
                    className="avatar-mascot-img"
                    style={{ width: "auto", height: "auto" }}
                  />
                </div>
              )}

              <div
                className={`chat-bubble-container ${
                  m.sender === "user" ? "user-bubble-wrap" : "assistant-bubble-wrap"
                }`}
              >
                <div
                  className={`chat-bubble ${m.sender === "user" ? "user-bubble" : "assistant-bubble"}`}
                >
                  <div className="chat-bubble-text">
                    {m.sender === "assistant" ? (
                      <FormattedMessageText text={m.text} />
                    ) : (
                      m.text
                    )}
                  </div>
                </div>

                {/* Structured "Safer plan" Card for assistant advice if available */}
                {m.recommendation && targetTripId && (
                  <div className="safer-plan-card">
                    <div className="safer-plan-header">
                      <div className="safer-plan-icon-wrap">
                        <IconShield width={18} height={18} />
                      </div>
                      <div className="safer-plan-titles">
                        <h3 className="safer-plan-heading">
                          แผนการเดินทางที่ปลอดภัยกว่า (Safer plan)
                        </h3>
                        <p className="safer-plan-sub">คำแนะนำเพื่อลดความเสี่ยงในการเดินทางของคุณ:</p>
                      </div>
                    </div>

                    <div className="safer-plan-body">
                      <ol className="safer-plan-steps">
                        {m.recommendation.immediate_actions?.map((action, index) => (
                          <li key={`${m.id}-${index}`}>
                            <span className="step-num">{index + 1}</span>
                            <span className="step-text">{action.text}</span>
                          </li>
                        ))}
                      </ol>

                      <div className="safer-plan-mascot-col">
                        <Image
                          src="/assets/mascot/mascot-welcome.png"
                          width={95}
                          height={110}
                          alt="มาสคอตช้าง"
                          className="safer-plan-mascot-img"
                          style={{ width: "auto", height: "auto" }}
                        />
                      </div>
                    </div>

                    <Link
                      href={`/trips/${targetTripId}/compare`}
                      className="update-trip-action-btn"
                    >
                      <span className="btn-icon">
                        <IconRoute width={16} height={16} />
                      </span>
                      <span>อัปเดตแผนการเดินทางของฉัน</span>
                      <span className="btn-arrow">›</span>
                    </Link>
                  </div>
                )}

                <div className="chat-meta-row">
                  <span className="chat-time">{m.timestamp}</span>
                  {m.sender === "user" && (
                    <span className="read-receipt" aria-hidden="true">
                      ✓✓
                    </span>
                  )}
                </div>
              </div>

              {m.sender === "user" && (
                <div className="user-avatar-badge" aria-hidden="true">
                  <div className="user-avatar-circle">
                    <IconUser width={18} height={18} />
                  </div>
                </div>
              )}
            </div>
          ))}

          {/* AI Generating Indicator */}
          {isSending && (
            <div className="chat-bubble-row assistant-row">
              <div className="assistant-avatar-badge" aria-hidden="true">
                <Image
                  src="/assets/mascot/mascot-welcome.png"
                  width={40}
                  height={40}
                  alt=""
                  className="avatar-mascot-img"
                  style={{ width: "auto", height: "auto" }}
                />
              </div>
              <div className="chat-bubble assistant-bubble streaming-bubble">
                <div className="streaming-spinner">
                  <span className="dot dot-1" />
                  <span className="dot dot-2" />
                  <span className="dot dot-3" />
                </div>
                <span className="streaming-stage-text">
                  Gemini กำลังวิเคราะห์ข้อมูลและสร้างคำตอบ…
                </span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Quick Prompts Chips */}
        <div className="quick-prompts-row">
          {QUICK_PROMPTS.map((prompt) => (
            <button
              key={prompt.label}
              type="button"
              className="prompt-pill-btn"
              onClick={() => handleSendMessage(prompt.query)}
              disabled={isSending}
            >
              <span className="pill-icon">
                {prompt.icon === "route" && <IconRoute width={14} height={14} />}
                {prompt.icon === "weather" && <IconCloudRain width={14} height={14} />}
                {prompt.icon === "emergency" && <IconAlertTriangle width={14} height={14} />}
              </span>
              <span>{prompt.label}</span>
            </button>
          ))}
        </div>

        {/* Bottom Chat Input Form */}
        <form
          className="assistant-bottom-input-bar"
          onSubmit={(e) => {
            e.preventDefault();
            void handleSendMessage(inputValue);
          }}
        >
          <span className="input-clip-icon" aria-hidden="true">
            <IconPaperclip width={18} height={18} />
          </span>
          <input
            type="text"
            className="assistant-input-field"
            placeholder="Type your travel safety question in English or Thai… / พิมพ์คำถามของคุณที่นี่..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            disabled={isSending}
            aria-label="พิมพ์คำถามถึงผู้ช่วย"
          />
          <button
            type="submit"
            className="assistant-send-circle"
            disabled={isSending || !inputValue.trim()}
            aria-label="ส่งข้อความ"
          >
            <IconSend width={16} height={16} />
          </button>
        </form>
      </section>

      {/* =======================================================================
          COLUMN 3: TRIP CONTEXT SIDEBAR
          ======================================================================= */}
      <aside className="assistant-context-card" aria-label="บริบทและสถานะของทริป">
        {/* Header */}
        <div className="context-card-header">
          <IconMapPin width={18} height={18} className="context-pin-icon" aria-hidden="true" />
          <h2 className="context-card-heading">บริบทของทริป (Trip context)</h2>
        </div>

        {/* Mini Map Route Preview */}
        <div className="context-minimap-card">
          <Image
            src="/assets/illustrations/global-map-background.png"
            alt="แผนที่แนวเส้นทางการเดินทาง"
            fill
            className="context-minimap-bg"
            sizes="300px"
          />
          <div className="context-minimap-overlay">
            <div className="minimap-route-visual">
              <span className="route-node origin-node" title="จุดเริ่มต้น" />
              <div className="route-dashed-line" />
              <span className="route-node dest-node" title="จุดหมายปลายทาง" />
            </div>
          </div>
        </div>

        <div className="context-metrics-list">
          {activeTrip ? (
            <Link href={`/trips/${activeTrip.trip_id}`} className="context-metric-row">
              {activeTrip.origin.display_name} → {activeTrip.destination.display_name}
              <span>ดูสถานะทริปและผลประเมิน</span>
            </Link>
          ) : (
            <p>ยังไม่มีทริปที่กำลังเดินทาง ข้อมูลความเสี่ยงและสภาพอากาศของทริปยังไม่พร้อม</p>
          )}
        </div>

        {/* Live Location Toggle Box */}
        <div className="context-location-toggle-box">
          <div className="location-toggle-header">
            <div className="location-title-group">
              <IconMapPin width={16} height={16} className="loc-pin" />
              <span className="loc-title">ใช้ตำแหน่งสด (Live location)</span>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={liveLocationEnabled}
              className={`location-switch-btn ${liveLocationEnabled ? "active" : ""}`}
              onClick={toggleLiveLocation}
            >
              <span className="switch-thumb" />
            </button>
          </div>
          <p className="location-toggle-desc">
            {liveLocationEnabled && liveLocationCoords
              ? `พิกัดปัจจุบัน: ${liveLocationCoords.lat.toFixed(4)}, ${liveLocationCoords.lng.toFixed(4)}`
              : "รับคำแนะนำที่แม่นยำและทันเวลาโดยอิงตามตำแหน่งปัจจุบันของคุณ"}
          </p>
        </div>

        {/* Decorative Bottom Illustration Banner */}
        <div className="context-bottom-decorative">
          <Image
            src="/assets/illustrations/hero-global-travel-banner.png"
            alt="ทิวทัศน์ธรรมชาติ"
            fill
            className="decorative-scenic-img"
            sizes="300px"
          />
        </div>
      </aside>
    </div>
  );
}
