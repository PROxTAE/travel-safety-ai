# SafetyTravel Assistant — Discord Asset Pack

ชุดภาพสำหรับ Discord bot ที่ใช้ธีมเดียวกับ SafetyTravel Assistant ในโปรเจกต์: พื้นหลังสว่าง สี mint/teal/navy, accent สีส้ม, ภาพท่องเที่ยว และมาสคอตช้างตัวเดิม

## Discord Developer Portal

- **App Icon:** `safetytravel-app-icon.png`
- **Name:** `SafetyTravel Assistant`
- **Description:**

  `SafetyTravel Assistant ช่วยทีมวางแผนและดูแลความปลอดภัยในการเดินทาง พร้อมแจ้งงาน กำหนดส่ง สถานะ Pull Request และ CI/CD ผ่าน Discord เพื่อให้ทุกคนประสานงานและตอบสนองต่อเหตุการณ์สำคัญได้จากที่เดียว`

- **Tags:** `travel`, `safety`, `productivity`, `teamwork`, `automation`
- **Interactions Endpoint URL:** เว้นว่างเมื่อใช้ Gateway ผ่าน discord.js/discord.py; หากรับ interactions ผ่าน HTTP ให้ใช้ public HTTPS endpoint เช่น `https://bot.example.com/api/discord/interactions`
- **Linked Roles Verification URL:** เว้นว่างหากไม่ได้ใช้ Linked Roles
- **Terms of Service URL / Privacy Policy URL:** เว้นได้ระหว่างใช้ภายในทีม แต่ควรมี URL จริงก่อนเปิดบอทสู่สาธารณะ

ห้าม commit Bot Token, client secret หรือ webhook secret ลง Git

## Brand palette

- Mint `#25C7AE`
- Teal `#0FA78F`
- Navy `#103653`
- Sky `#73D7E8`
- Orange `#FF8A1F`
- Alert Coral `#F05252`

## Assets

| File | Purpose | Embed color |
|---|---|---:|
| `safetytravel-app-icon.png` | Recommended App Icon: smiling mascot head, exact 1024x1024 | `0x25C7AE` |
| `safetytravel-logo-app-icon.png` | Previous compass/shield logo icon | `0x25C7AE` |
| `safetytravel-mascot-app-icon-master.png` | High-resolution mascot icon master | — |
| `safetytravel-logo-horizontal.png` | Horizontal brand lockup | — |
| `mascot-welcome.png` | Welcome, help, onboarding | `0x25C7AE` |
| `mascot-warning.png` | Warning or degraded status | `0xFF8A1F` |
| `mascot-emergency-help.png` | Emergency workflow | `0xF05252` |
| `embed-announcement.png` | General announcement | `0x25C7AE` |
| `embed-task-assigned.png` | New task / assignment | `0x25C7AE` |
| `embed-deadline-reminder.png` | Due-date reminder | `0xFF8A1F` |
| `embed-pr-review.png` | PR opened / review requested | `0x7657D6` |
| `embed-pr-merged.png` | PR approved / merged | `0x10B981` |
| `embed-deploy-success.png` | Deployment succeeded | `0x10B981` |
| `embed-build-failed.png` | CI/build failed | `0xF05252` |
| `embed-weekly-summary.png` | Daily/weekly progress digest | `0x25C7AE` |

ภาพ embed ทุกใบเป็น PNG ขนาด 2172x724 อัตราส่วน 3:1 และไม่มีข้อความ เพื่อให้ title, description และ fields ใน Discord เป็นแหล่งข้อความหลัก

## discord.js example

```js
import { AttachmentBuilder, EmbedBuilder } from "discord.js";

const image = new AttachmentBuilder(
  "assets/safetytravel-discord/embed-pr-review.png",
  { name: "safetytravel-pr-review.png" },
);

const embed = new EmbedBuilder()
  .setColor(0x7657d6)
  .setTitle("Pull request ready for review")
  .setDescription("PR #128 · feat/safe-route")
  .addFields(
    { name: "Author", value: "@teammate", inline: true },
    { name: "Reviewers", value: "@reviewer-1, @reviewer-2", inline: true },
    { name: "Checks", value: "3/3 passed", inline: true },
  )
  .setImage("attachment://safetytravel-pr-review.png")
  .setTimestamp();

await channel.send({ embeds: [embed], files: [image] });
```

ใช้ `asset-map.json` เพื่อเลือกไฟล์และสีตาม event type จากจุดเดียว
