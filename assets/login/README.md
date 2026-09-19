# Login Page Asset Pack

ชุดไฟล์สำหรับประกอบ `assets/ui-screens/00-login.png` เป็นหน้าเว็บจริง โดยแยกภาพออกจากข้อความ ฟอร์ม ปุ่ม และ card เพื่อให้หน้า responsive และ accessible

## Components

| File | Size | Usage |
| --- | ---: | --- |
| `backgrounds/login-hero-background.png` | 1254 × 1254 | พื้นหลังฝั่ง illustration ใช้ `object-fit: cover` หรือ `background-size: cover` |
| `decorations/login-route-overlay.png` | 2172 × 724 | เครื่องบิน เส้นทาง และหมุด วางแบบ absolute เหนือ hero background |
| `decorations/login-mascot-welcome.png` | 1145 × 1374 | มาสคอตฝั่งซ้าย พื้นหลังโปร่งใส |
| `decorations/login-corner-decoration.png` | 1536 × 1024 | ใบไม้/เนินมิ้นต์มุมขวาล่างของ form panel |
| `brand/login-logo-horizontal.png` | 2172 × 724 | โลโก้สำหรับ desktop/tablet header |
| `brand/login-logo-mark.png` | 1254 × 1254 | โลโก้ย่อสำหรับ mobile, favicon หรือ loading state |
| `icons/login-icon-sheet.png` | 1774 × 887 | sprite sheet ต้นฉบับ 4 × 2 |
| `icons/*.png` | 444 × 444 | ไอคอนเดี่ยวพื้นหลังโปร่งใส |

## Individual icons

- `icons/email.png`
- `icons/password-lock.png`
- `icons/show-password.png`
- `icons/language-globe.png`
- `icons/sso-users.png`
- `icons/checked-square.png`
- `icons/arrow-right.png`
- `icons/sos-shield.png`

## Recommended layer order

1. `login-hero-background.png`
2. HTML headline and supporting copy
3. `login-route-overlay.png`
4. `login-mascot-welcome.png`
5. Form panel and all interactive HTML controls
6. `login-corner-decoration.png` behind the form content

## Build guidance

- Headline, input labels, placeholders, links, buttons, checkbox, divider และ error messages ควรเป็น HTML/CSS ไม่ควรรวมอยู่ในรูป
- Desktop: hero panel ประมาณ `52%`, form panel `48%`
- Mobile: ซ่อน full hero background หรือย่อเป็นแถบด้านบน แล้วใช้ `login-logo-mark.png` กับ mascot ขนาดเล็ก
- โลโก้และไอคอนควรใช้ `object-fit: contain`
- ไอคอนฟอร์มแนะนำให้แสดงที่ `20–24px`; SSO และ SOS ใช้ `22–28px`
- Route overlay, mascot และ corner decoration ควรใช้ `pointer-events: none`
- Emergency Center ต้องเปิดได้โดยไม่ต้องผ่าน authentication

ข้อมูลชื่อไฟล์สำหรับ import แบบอัตโนมัติอยู่ใน `manifest.json`

