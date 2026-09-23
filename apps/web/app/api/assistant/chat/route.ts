import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

interface ChatMessage {
  role: "user" | "assistant" | "model" | "system";
  content: string;
}

interface TripContext {
  trip_id?: string;
  title?: string;
  origin?: {
    display_name?: string;
    lat?: number;
    lon?: number;
  };
  destination?: {
    display_name?: string;
    lat?: number;
    lon?: number;
  };
  departure_time?: string;
  arrival_time?: string;
  travel_mode?: string;
  status?: string;
  risk_level?: string;
  safety_score?: number;
  short_summary?: string;
  reasons?: Array<{ code?: string; text?: string; severity?: string }>;
  immediate_actions?: Array<{ code?: string; text?: string }>;
  weather?: Record<string, unknown>;
}

interface LiveLocation {
  lat: number;
  lng: number;
  address?: string;
}

interface RequestBody {
  messages: ChatMessage[];
  tripContext?: TripContext | null;
  liveLocation?: LiveLocation | null;
  locale?: string;
}

const FALLBACK_MODELS = [
  process.env.GEMINI_MODEL || "gemini-3.6-flash",
  "gemini-3.6-flash",
  "gemini-2.5-flash",
  "gemini-flash-latest",
  "gemini-3.5-flash",
];

function buildSystemPrompt(
  tripContext?: TripContext | null,
  liveLocation?: LiveLocation | null,
  locale: string = "th",
): string {
  let contextSection = "";

  if (tripContext && (tripContext.origin || tripContext.destination)) {
    const originName = tripContext.origin?.display_name || "ไม่ระบุ";
    const destName = tripContext.destination?.display_name || "ไม่ระบุ";
    const mode = tripContext.travel_mode || "ไม่ระบุ";
    const depTime = tripContext.departure_time || "ตามกำหนดการ";
    const summary = tripContext.short_summary || "อยู่ระหว่างการประเมิน";

    contextSection += `
[บริบททริปปัจจุบันของผู้ใช้ (Active Trip Context)]
- ต้นทาง (Origin): ${originName}
- ปลายทาง (Destination): ${destName}
- รูปแบบการเดินทาง (Travel Mode): ${mode}
- เวลาเดินทาง (Departure): ${depTime}
- สรุปสถานะความปลอดภัย (Safety Summary): ${summary}
`;

    if (tripContext.reasons && tripContext.reasons.length > 0) {
      contextSection += `- ปัจจัยความเสี่ยงที่พบ: ${tripContext.reasons.map((r) => r.text || r.code).join(", ")}\n`;
    }
    if (tripContext.immediate_actions && tripContext.immediate_actions.length > 0) {
      contextSection += `- ข้อแนะนำเพื่อความปลอดภัย: ${tripContext.immediate_actions.map((a) => a.text).join("; ")}\n`;
    }
  } else {
    contextSection += `
[บริบททริปปัจจุบันของผู้ใช้]
- ขณะนี้ผู้ใช้ยังไม่ได้เลือกทริปเฉพาะเจาะจง สามารถพูดคุยทั่วไป แนะนำสถานที่ท่องเที่ยว แนะนำการเตรียมตัวเดินทาง หรือสอบถามจุดหมายที่ผู้ใช้สนใจได้
`;
  }

  if (liveLocation) {
    contextSection += `
[ตำแหน่งปัจจุบันของผู้ใช้ (Live Location)]
- พิกัด: ละติจูด ${liveLocation.lat.toFixed(5)}, ลองจิจูด ${liveLocation.lng.toFixed(5)}
${liveLocation.address ? `- สถานที่ใกล้เคียง: ${liveLocation.address}` : ""}
`;
  }

  const baseInstructions = `
คุณคือ "Smart Travel Assistant" (ผู้ช่วยการเดินทางอัจฉริยะ) เพื่อนร่วมทาง AI ผู้เชี่ยวชาญด้านการเดินทาง ท่องเที่ยว และความปลอดภัยในการเดินทางทั้งในประเทศไทยและต่างประเทศ

${contextSection}

[เบอร์โทรศัพท์และศูนย์ช่วยเหลือฉุกเฉินสำคัญในประเทศไทย]
- ตำรวจท่องเที่ยว (Tourist Police): 1155 (บริการหลายภาษา 24 ชม.)
- แพทย์ฉุกเฉิน / กู้ชีพ (EMS Thailand): 1669
- เหตุด่วนเหตุร้าย / ตำรวจ (Police): 191
- ตำรวจทางหลวง (Highway Police): 1193
- กรมป้องกันและบรรเทาสาธารณภัย (ปภ. แจ้งภัยพิบัติ): 1784
- ศูนย์เตือนภัยพิบัติแห่งชาติ: 192
- การรถไฟแห่งประเทศไทย: 1690

[แนวทางการตอบและบุคลิกภาพ]
1. ภาษาและน้ำเสียง:
   - สุภาพ เป็นกันเอง อบอุ่น กระตือรือร้น ให้คำแนะนำอย่างมืออาชีพ (ลงท้ายด้วย "ครับ/ค่ะ" อย่างเหมาะสม)
   - หากผู้ใช้ถามภาษาไทย ให้ตอบภาษาไทยที่อ่านง่ายและชัดเจน หากถามภาษาอื่นให้ตอบภาษานั้นๆ
2. ความสามารถในการสนทนา:
   - **พูดคุยทั่วไป & ท่องเที่ยว (General Chat)**: สามารถทักทาย ชวนคุย แนะนำที่เที่ยว แนะนำของกินท้องถิ่น การจัดกระเป๋า สภาพอากาศ และวัฒนธรรมท้องถิ่นได้อย่างลื่นไหล
   - **ใช้บริบททริป (Trip Context)**: หากผู้ใช้ถามเรื่องความปลอดภัย เส้นทาง หรือสภาพอากาศ ให้นำข้อมูลทริปปัจจุบัน (${tripContext?.origin?.display_name || "ต้นทาง"} → ${tripContext?.destination?.display_name || "ปลายทาง"}) มาวิเคราะห์และให้คำตอบที่สอดคล้องอย่างชาญฉลาด
   - **ความปลอดภัยและการแจ้งเตือน (Safety First)**: หากพบหรือผู้ใช้สอบถามถึงความเสี่ยง (ฝนตกหนัก น้ำท่วม ดินสไลด์ ถนนปิด หรืออุบัติเหตุ) ให้แนะนำขั้นตอนรับมือที่ชัดเจน พร้อมเบอร์ติดต่อฉุกเฉินที่เกี่ยวข้องเสมอ
3. รูปแบบการจัดหน้า:
   - ใช้ Markdown เช่น ตัวหนา (**หัวข้อ**), รายการ bullet points (-), หรือตัวเลขอธิบายเป็นข้อๆ เพื่อให้อ่านง่าย สบายตา
`;

  return baseInstructions.trim();
}

export async function POST(req: NextRequest) {
  try {
    const apiKey = process.env.GEMINI_API_KEY || "";

    if (!apiKey) {
      return NextResponse.json(
        { error: "GEMINI_API_KEY is not configured." },
        { status: 500 },
      );
    }

    const body = (await req.json()) as RequestBody;
    const { messages = [], tripContext = null, liveLocation = null, locale = "th" } = body;

    if (!messages || messages.length === 0) {
      return NextResponse.json(
        { error: "Messages array cannot be empty." },
        { status: 400 },
      );
    }

    const systemPrompt = buildSystemPrompt(tripContext, liveLocation, locale);

    // Format messages for Gemini API
    // Ensure alternating user/model roles and clean structure
    const contents: Array<{ role: "user" | "model"; parts: Array<{ text: string }> }> = [];

    for (const msg of messages) {
      if (msg.role === "system") continue;
      const role: "user" | "model" = msg.role === "assistant" || msg.role === "model" ? "model" : "user";
      
      // Merge consecutive identical roles if any
      if (contents.length > 0 && contents[contents.length - 1].role === role) {
        contents[contents.length - 1].parts[0].text += `\n\n${msg.content}`;
      } else {
        contents.push({
          role,
          parts: [{ text: msg.content }],
        });
      }
    }

    // Ensure the conversation starts with user role
    if (contents.length > 0 && contents[0].role === "model") {
      contents.unshift({
        role: "user",
        parts: [{ text: "สวัสดีครับ" }],
      });
    }

    // Deduplicate models to try
    const modelsToTry = Array.from(new Set(FALLBACK_MODELS.filter(Boolean)));
    let lastError: string | null = null;
    let successfulReply: string | null = null;
    let usedModel: string | null = null;

    for (const model of modelsToTry) {
      try {
        const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;

        const payload = {
          systemInstruction: {
            parts: [{ text: systemPrompt }],
          },
          contents,
          generationConfig: {
            temperature: 0.7,
            topK: 40,
            topP: 0.95,
            maxOutputTokens: 2048,
          },
        };

        const res = await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
          signal: AbortSignal.timeout(25_000),
        });

        if (res.ok) {
          const data = (await res.json()) as {
            candidates?: Array<{
              content?: {
                parts?: Array<{ text?: string }>;
              };
            }>;
          };

          const text = data.candidates?.[0]?.content?.parts?.[0]?.text;
          if (text) {
            successfulReply = text;
            usedModel = model;
            break;
          }
        } else {
          const errData = await res.json().catch(() => ({}));
          lastError = `Model ${model} returned HTTP ${res.status}: ${JSON.stringify(errData)}`;
        }
      } catch (err) {
        lastError = `Model ${model} failed: ${err instanceof Error ? err.message : String(err)}`;
      }
    }

    if (!successfulReply) {
      return NextResponse.json(
        {
          error: "Failed to generate response from Gemini API.",
          details: lastError,
        },
        { status: 502 },
      );
    }

    return NextResponse.json({
      reply: successfulReply,
      model: usedModel,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: "Internal server error handling chat request.",
        details: error instanceof Error ? error.message : String(error),
      },
      { status: 500 },
    );
  }
}
