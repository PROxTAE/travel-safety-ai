# travel-safety-ai

ระบบผู้ช่วย AI ด้านความปลอดภัยในการเดินทาง

## โครงสร้าง branch

| Branch      | ใช้ทำอะไร                              | push ตรงได้ไหม |
|-------------|-----------------------------------------|----------------|
| `main`      | โค้ดที่พร้อมใช้งานจริง (stable)          | ไม่ได้ ต้องทำ PR จาก `dev` |
| `dev`       | โค้ดที่รวมงานของทุกคนแล้ว                | ไม่ได้ ต้องทำ PR จาก `feature/*` |
| `feature/*` | งานย่อยของแต่ละคน เช่น `feature/login`  | ได้ push ตรงเลย |

## กติกาการส่งงาน

1. แตก branch ใหม่จาก `dev` เสมอ ชื่อขึ้นต้นด้วย `feature/`
2. เปิด Pull Request เข้า `dev`
3. ต้องมีคน approve อย่างน้อย 1 คน และ comment ทุกอันต้องถูก resolve
4. CI ต้องผ่านสีเขียวก่อน merge
5. เมื่อ `dev` พร้อมปล่อยจริง จึงเปิด PR จาก `dev` เข้า `main` เท่านั้น

## วิธีเริ่มงาน

```bash
git clone https://github.com/Mrbeer19/travel-safety-ai.git
cd travel-safety-ai
git checkout dev
git pull
git checkout -b feature/ชื่องานของคุณ
```

<!-- ทดสอบว่า feature/* push ได้ -->
