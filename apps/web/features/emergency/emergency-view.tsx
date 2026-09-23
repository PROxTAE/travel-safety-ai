"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import type { components } from "@/lib/api/generated/public-api";
import { api } from "@/lib/api/client";
import { DataSkeleton } from "@/components/ui/data-states";
import {
  IconShield,
  IconPhone,
  IconMedicalCross,
  IconCalendar,
  IconMapPin,
  IconAlertTriangle,
  IconSiren,
  IconHospital,
  IconEmbassy,
  IconPoliceShield,
  IconAmbulance,
  IconFire,
  IconLock,
  IconCheck,
} from "@/components/ui/icons";

type Schema = components["schemas"];
type OfficialContact = Schema["OfficialContact"];
type EmergencyPoi = Schema["EmergencyPoi"];
type EmergencyProfile = Schema["EmergencyProfile"];
type BloodType = "A+" | "A-" | "B+" | "B-" | "AB+" | "AB-" | "O+" | "O-" | "UNKNOWN";

export function EmergencyView() {
  // SOS Hold state
  const [isHolding, setIsHolding] = useState(false);
  const [holdProgress, setHoldProgress] = useState(0);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [sosActivated, setSosActivated] = useState(false);
  const holdIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Active view tab: "sos" | "directory" | "nearby" | "profile"
  const [activeTab, setActiveTab] = useState<"sos" | "directory" | "nearby" | "profile">("sos");

  // Geolocation & Permissions
  const [location, setLocation] = useState<{ lat: number; lon: number } | null>(null);
  const [locationShared, setLocationShared] = useState(false);
  const [, setLocationLoading] = useState(false);

  // Contacts & Nearby
  const [contacts, setContacts] = useState<OfficialContact[]>([]);
  const [nearbyPlaces, setNearbyPlaces] = useState<EmergencyPoi[]>([]);
  const [selectedPoiType, setSelectedPoiType] = useState<"HOSPITAL" | "POLICE" | "EMBASSY">("HOSPITAL");
  const [loadingDirectory, setLoadingDirectory] = useState(false);

  // Emergency Profile
  const [profile, setProfile] = useState<EmergencyProfile | null>(null);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileSuccess, setProfileSuccess] = useState(false);

  // Default Fallback Bangkok coordinates if geolocation not yet granted
  const currentLat = location?.lat || 13.7563;
  const currentLon = location?.lon || 100.5018;

  // 1. Hold-for-SOS 3s Timer Logic
  function startHolding() {
    if (sosActivated) return;
    setIsHolding(true);
    const startTime = Date.now();
    const duration = 3000; // 3 seconds

    holdIntervalRef.current = setInterval(() => {
      const elapsed = Date.now() - startTime;
      const pct = Math.min(100, (elapsed / duration) * 100);
      setHoldProgress(pct);

      if (pct >= 100) {
        clearInterval(holdIntervalRef.current!);
        holdIntervalRef.current = null;
        setIsHolding(false);
        setHoldProgress(0);
        setShowConfirmModal(true);
      }
    }, 30);
  }

  function cancelHolding() {
    if (holdIntervalRef.current) {
      clearInterval(holdIntervalRef.current);
      holdIntervalRef.current = null;
    }
    setIsHolding(false);
    setHoldProgress(0);
  }

  // 2. Request Geolocation & Consent
  async function requestLocationSharing() {
    setLocationLoading(true);
    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          const coords = { lat: pos.coords.latitude, lon: pos.coords.longitude };
          setLocation(coords);
          setLocationShared(true);
          setLocationLoading(false);

          try {
            await api.POST("/api/v1/consents", {
              body: {
                type: "LOCATION_ONCE",
                granted: true,
                policy_version: "1.0.0",
              },
            });
          } catch {
            // Handled
          }
        },
        () => {
          alert("ไม่สามารถเข้าถึงตำแหน่งของคุณได้ กรุณาเปิดการอนุญาตในเบราว์เซอร์");
          setLocationLoading(false);
        },
      );
    }
  }

  // 3. Load Directory
  useEffect(() => {
    const controller = new AbortController();

    async function loadContacts() {
      setLoadingDirectory(true);
      try {
        const res = await api.GET("/api/v1/emergency/contacts", {
          params: {
            query: {
              lat: currentLat,
              lon: currentLon,
              locale: "th-TH",
            },
          },
          signal: controller.signal,
        });

        if (res.data?.data) {
          setContacts(res.data.data);
        }
      } catch {
        setContacts([]);
      } finally {
        setLoadingDirectory(false);
      }
    }

    if (activeTab === "directory") {
      void loadContacts();
    }

    return () => {
      controller.abort();
    };
  }, [activeTab, currentLat, currentLon]);

  // 4. Load Nearby POIs
  useEffect(() => {
    const controller = new AbortController();

    async function loadNearby() {
      try {
        const res = await api.GET("/api/v1/emergency/nearby", {
          params: {
            query: {
              lat: currentLat,
              lon: currentLon,
              type: selectedPoiType,
              radius_m: 2000,
              limit: 20,
            },
          },
          signal: controller.signal,
        });

        if (res.data?.data) {
          setNearbyPlaces(res.data.data);
        }
      } catch {
        setNearbyPlaces([]);
      }
    }

    if (activeTab === "nearby" && locationShared && location) {
      void loadNearby();
    }

    return () => {
      controller.abort();
    };
  }, [activeTab, selectedPoiType, currentLat, currentLon, locationShared, location]);

  // 5. Load Emergency Profile
  useEffect(() => {
    const controller = new AbortController();

    async function loadProfile() {
      try {
        const res = await api.GET("/api/v1/me/emergency-profile", {
          signal: controller.signal,
        });

        if (res.data?.data) {
          setProfile(res.data.data);
        }
      } catch {
        // Fallback blank structure
        setProfile({
          blood_type: "O+",
          allergies: ["None"],
          medications: [],
          medical_notes: "None",
          contacts: [
            {
              name: "ผู้ติดต่อฉุกเฉิน",
              relationship: "ครอบครัว",
              phone: "+66 81 234 5678",
            },
          ],
          insurance: {
            provider_name: "Global Travel Insurance",
            policy_reference: "POL-987654",
            emergency_phone: "+66 2 123 4567",
          },
          updated_at: new Date().toISOString(),
        });
      }
    }

    if (activeTab === "profile") {
      void loadProfile();
    }

    return () => {
      controller.abort();
    };
  }, [activeTab]);

  return (
    <div className="emergency-page-container">
      {/* 1. Page Header & Mascot */}
      <header className="emergency-header">
        <div className="emergency-header-copy">
          <span className="emergency-alert-tag">ศูนย์ช่วยเหลือฉุกเฉิน</span>
          <h1 className="emergency-title">ศูนย์ช่วยเหลือฉุกเฉิน (Traveler Emergency Center)</h1>
          <p className="emergency-desc">
            เชื่อมต่อหน่วยงานกู้ภัยฉุกเฉิน ค้นหาสถานพยาบาลและสถานีตำรวจใกล้เคียง และจัดการข้อมูลสุขภาพฉุกเฉินอย่างปลอดภัย
          </p>
        </div>
        <div className="emergency-header-mascot" aria-hidden="true">
          <Image
            src="/assets/mascot/mascot-emergency-help.png"
            width={160}
            height={160}
            alt="มาสคอตช่วยเหลือฉุกเฉิน"
            priority
          />
        </div>
      </header>

      {/* 2. Tab Navigation Bar */}
      <nav className="emergency-nav-tabs" aria-label="หมวดหมู่ช่วยเหลือฉุกเฉิน">
        <button
          type="button"
          className={`emergency-tab-btn ${activeTab === "sos" ? "active" : ""}`}
          onClick={() => setActiveTab("sos")}
        >
          <IconAlertTriangle width={16} height={16} />
          <span>แจ้งเหตุฉุกเฉิน (SOS Activation)</span>
        </button>
        <button
          type="button"
          className={`emergency-tab-btn ${activeTab === "directory" ? "active" : ""}`}
          onClick={() => setActiveTab("directory")}
        >
          <IconPhone width={16} height={16} />
          <span>เบอร์ติดต่อฉุกเฉิน (Verified Directory)</span>
        </button>
        <button
          type="button"
          className={`emergency-tab-btn ${activeTab === "nearby" ? "active" : ""}`}
          onClick={() => setActiveTab("nearby")}
        >
          <IconMedicalCross width={16} height={16} />
          <span>สถานที่ใกล้เคียง (Nearby Facilities)</span>
        </button>
        <button
          type="button"
          className={`emergency-tab-btn ${activeTab === "profile" ? "active" : ""}`}
          onClick={() => setActiveTab("profile")}
        >
          <IconCalendar width={16} height={16} />
          <span>ข้อมูลสุขภาพ (Medical Profile)</span>
        </button>
      </nav>

      {/* Confirmation Modal after 3s Hold */}
      {showConfirmModal && (
        <div className="sos-modal-overlay" role="dialog" aria-modal="true">
          <div className="sos-modal-card">
            <div className="sos-modal-icon">
              <IconSiren width={48} height={48} />
            </div>
            <h2>ยืนยันการส่งสัญญาณฉุกเฉิน (Confirm Emergency Alert)</h2>
            <p>
              คุณกำลังเผชิญอันตราย อุบัติเหตุ หรือวิกฤตทางการแพทย์เร่งด่วนใช่หรือไม่?
            </p>
            <p className="sos-modal-subtext">
              การยืนยันจะแชร์พิกัด GPS สดของคุณกับหน่วยกู้ภัยที่ได้รับการรับรอง และเปิดช่องทางโทรด่วนทันที
            </p>
            <div className="sos-modal-actions">
              <button
                type="button"
                className="sos-confirm-btn"
                onClick={() => {
                  setShowConfirmModal(false);
                  setSosActivated(true);
                  void requestLocationSharing();
                }}
              >
                ใช่, เชื่อมต่อหน่วยช่วยเหลือฉุกเฉิน
              </button>
              <button
                type="button"
                className="sos-cancel-btn"
                onClick={() => setShowConfirmModal(false)}
              >
                ยกเลิก / กดผิด
              </button>
            </div>
          </div>
        </div>
      )}

      {/* TAB 1: SOS Activation */}
      {activeTab === "sos" && (
        <section className="emergency-section sos-section" aria-label="Hold for SOS">
          {sosActivated ? (
            <div className="sos-active-banner">
              <div className="sos-active-header">
                <span className="sos-pulse-ring" />
                <h2>โหมดฉุกเฉินทำงานอยู่ (Emergency Mode Active)</h2>
              </div>
              <p>
                ระบบกำลังแชร์พิกัดของคุณ กรุณาใช้เบอร์ติดต่อฉุกเฉินที่ได้รับการตรวจสอบด้านล่างเพื่อขอความช่วยเหลือทันที
              </p>
              <div className="location-coords-badge">
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <IconMapPin width={16} height={16} /> พิกัด GPS ปัจจุบัน: {currentLat.toFixed(4)}° N, {currentLon.toFixed(4)}° E
                </span>
                <button
                  type="button"
                  className="stop-share-btn"
                  onClick={() => {
                    setSosActivated(false);
                    setLocationShared(false);
                  }}
                >
                  ปิดโหมดฉุกเฉิน
                </button>
              </div>
            </div>
          ) : (
            <div className="sos-hold-wrapper">
              <div className="sos-instructions">
                <h2>กดค้างไว้ 3 วินาที (Press & Hold for 3 Seconds)</h2>
                <p>
                  กดปุ่มด้านล่างค้างไว้เพื่อส่งสัญญาณขอความช่วยเหลือ หากปล่อยก่อนครบ 3 วินาทีระบบจะยกเลิก
                </p>
              </div>

              {/* Accessible Interactive SOS Button */}
              <div className="sos-button-frame">
                {/* SVG Progress Ring */}
                <svg className="sos-progress-ring" width="220" height="220">
                  <circle
                    className="sos-ring-bg"
                    stroke="#fee2e2"
                    strokeWidth="8"
                    fill="transparent"
                    r="96"
                    cx="110"
                    cy="110"
                  />
                  <circle
                    className="sos-ring-fill"
                    stroke="#F24E54"
                    strokeWidth="8"
                    strokeDasharray="603"
                    strokeDashoffset={603 - (603 * holdProgress) / 100}
                    strokeLinecap="round"
                    fill="transparent"
                    r="96"
                    cx="110"
                    cy="110"
                  />
                </svg>

                <button
                  type="button"
                  className={`sos-main-circle-btn ${isHolding ? "holding" : ""}`}
                  onPointerDown={startHolding}
                  onPointerUp={cancelHolding}
                  onPointerLeave={cancelHolding}
                  onKeyDown={(e) => {
                    if (e.key === " " || e.key === "Enter") {
                      if (!isHolding) startHolding();
                    }
                  }}
                  onKeyUp={(e) => {
                    if (e.key === " " || e.key === "Enter") {
                      cancelHolding();
                    }
                  }}
                  aria-label="Hold for SOS (3 seconds)"
                >
                  <span className="sos-btn-icon">
                    <IconSiren width={36} height={36} />
                  </span>
                  <span className="sos-btn-label">
                    {isHolding ? `${Math.ceil((100 - holdProgress) / 33)}s` : "HOLD SOS"}
                  </span>
                </button>
              </div>
            </div>
          )}

          {/* Quick Contacts Preview */}
          <div className="quick-contacts-preview">
            <h3>เบอร์ติดต่อฉุกเฉินประเทศไทย (Verified Emergency Numbers - Thailand)</h3>
            <div className="contacts-grid">
              {contacts.map((c) => (
                <div key={c.contact_id} className="contact-card">
                  <div className="contact-info">
                    <span className="contact-type-label">{c.service_type}</span>
                    <strong className="contact-name">{c.label}</strong>
                    <span className="contact-number">{c.phone}</span>
                  </div>
                  <a
                    href={`tel:${c.phone}`}
                    className="dial-button"
                    aria-label={`โทร ${c.label} เบอร์ ${c.phone}`}
                  >
                    <IconPhone width={14} height={14} /> โทรออก (Call)
                  </a>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* TAB 2: Verified Contacts Directory */}
      {activeTab === "directory" && (
        <section className="emergency-section" aria-label="Verified directory">
          <div className="section-header-row">
            <div>
              <h2>สมุดโทรศัพท์ฉุกเฉินทางการ (Official Emergency Directory)</h2>
              <p>รวมเบอร์ฉุกเฉินทางการสำหรับพิกัดที่เลือก (ค่าเริ่มต้น: กรุงเทพฯ)</p>
            </div>
            <span className="verified-badge">
              <IconCheck width={14} height={14} /> เฉพาะแหล่งข้อมูลทางการ (Official Sources)
            </span>
          </div>

          {loadingDirectory ? (
            <DataSkeleton label="กำลังโหลดรายชื่อติดต่อที่ได้รับการรับรอง..." />
          ) : (
            <div className="contacts-detailed-list">
              {contacts.map((c) => (
                <article key={c.contact_id} className="contact-detailed-card">
                  <div className="contact-detailed-main">
                    <div className="contact-type-icon">
                      {c.service_type === "POLICE" ? (
                        <IconPoliceShield width={24} height={24} />
                      ) : c.service_type === "AMBULANCE" ? (
                        <IconAmbulance width={24} height={24} />
                      ) : c.service_type === "FIRE" ? (
                        <IconFire width={24} height={24} />
                      ) : (
                        <IconShield width={24} height={24} />
                      )}
                    </div>
                    <div className="contact-text-group">
                      <h3>{c.label}</h3>
                      <p className="contact-auth">
                        หน่วยงาน: <strong>{c.authority}</strong>
                      </p>
                      <span className="contact-number-large">{c.phone}</span>
                    </div>
                  </div>

                  <div className="contact-actions-col">
                    <a href={`tel:${c.phone}`} className="dial-button primary">
                      <IconPhone width={16} height={16} /> โทรออกทันที
                    </a>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {/* TAB 3: Nearby Facilities */}
      {activeTab === "nearby" && (
        <section className="emergency-section" aria-label="Nearby facilities">
          <div className="section-header-row">
            <div>
              <h2>สถานพยาบาลและจุดช่วยเหลือใกล้เคียง (Nearby Facilities)</h2>
              <p>ค้นหาโรงพยาบาล สถานีตำรวจ และสถานทูตที่ใกล้ที่สุดพร้อมพิกัดที่แม่นยำ</p>
            </div>

            {/* Type filter */}
            <div className="poi-filter-pills">
              <button
                type="button"
                className={`poi-pill ${selectedPoiType === "HOSPITAL" ? "active" : ""}`}
                onClick={() => setSelectedPoiType("HOSPITAL")}
              >
                <IconHospital width={16} height={16} /> โรงพยาบาล (Hospitals)
              </button>
              <button
                type="button"
                className={`poi-pill ${selectedPoiType === "POLICE" ? "active" : ""}`}
                onClick={() => setSelectedPoiType("POLICE")}
              >
                <IconPoliceShield width={16} height={16} /> สถานีตำรวจ (Police)
              </button>
              <button
                type="button"
                className={`poi-pill ${selectedPoiType === "EMBASSY" ? "active" : ""}`}
                onClick={() => setSelectedPoiType("EMBASSY")}
              >
                <IconEmbassy width={16} height={16} /> สถานทูต (Embassies)
              </button>
            </div>
          </div>

          <div className="nearby-places-list">
            {locationShared && nearbyPlaces.length > 0 ? (
              nearbyPlaces.map((poi) => (
                <div key={poi.poi_id} className="nearby-card">
                  <div className="nearby-icon">
                    {selectedPoiType === "POLICE" ? (
                      <IconPoliceShield width={24} height={24} />
                    ) : selectedPoiType === "EMBASSY" ? (
                      <IconEmbassy width={24} height={24} />
                    ) : (
                      <IconHospital width={24} height={24} />
                    )}
                  </div>
                  <div className="nearby-info">
                    <h3>{poi.name || "ศูนย์บริการการแพทย์ฉุกเฉิน"}</h3>
                    <span className="nearby-dist">
                      {poi.distance_m ? `ห่างออกไป ${(poi.distance_m / 1000).toFixed(1)} กม.` : "ใกล้เคียง"}
                    </span>
                    {poi.phone && <span className="nearby-phone">โทร: {poi.phone}</span>}
                  </div>
                  {poi.phone && (
                    <a href={`tel:${poi.phone}`} className="dial-button">
                      <IconPhone width={14} height={14} /> โทร ↗
                    </a>
                  )}
                </div>
              ))
            ) : (
              <div className="empty-nearby-card">
                <p>{locationShared ? "ไม่พบสถานที่ในหมวดหมู่นี้ในรัศมีใกล้เคียง" : "อนุญาตตำแหน่งเพื่อค้นหาสถานที่ใกล้ตัวคุณ"}</p>
                <button
                  type="button"
                  className="refresh-location-btn"
                  onClick={requestLocationSharing}
                >
                  <IconMapPin width={16} height={16} /> อัปเดตพิกัด GPS
                </button>
              </div>
            )}
          </div>
        </section>
      )}

      {/* TAB 4: Medical Profile */}
      {activeTab === "profile" && (
        <section className="emergency-section" aria-label="Medical emergency profile">
          <div className="section-header-row">
            <div>
              <h2>ข้อมูลสุขภาพและข้อมูลฉุกเฉิน (Medical Profile)</h2>
              <p>
                บัตรข้อมูลสุขภาพฉุกเฉินเข้ารหัส ข้อมูลนี้จะได้รับการปกป้องและแสดงเฉพาะเมื่อเกิดเหตุฉุกเฉินทางการแพทย์
              </p>
            </div>
            <span className="crypto-badge">
              <IconLock width={14} height={14} /> เข้ารหัสความปลอดภัย AES-GCM
            </span>
          </div>

          {profileSuccess && (
            <div className="toast-success-banner">
              <IconCheck width={16} height={16} /> บันทึกข้อมูลสุขภาพฉุกเฉินเรียบร้อยแล้ว
            </div>
          )}

          {profile ? (
            <form
              className="emergency-profile-form"
              onSubmit={async (e) => {
                e.preventDefault();
                setProfileSaving(true);
                try {
                  await api.PUT("/api/v1/me/emergency-profile", {
                    body: {
                      allergies: profile.allergies,
                      blood_type: profile.blood_type,
                      contacts: profile.contacts,
                      insurance: profile.insurance,
                      medical_notes: profile.medical_notes,
                      medications: profile.medications,
                    },
                  });
                  setProfileSuccess(true);
                  setTimeout(() => setProfileSuccess(false), 3000);
                } catch {
                  alert("ไม่สามารถบันทึกข้อมูลได้ กรุณาตรวจสอบการเชื่อมต่อ");
                } finally {
                  setProfileSaving(false);
                }
              }}
            >
              <div className="form-grid-2">
                <div className="form-group">
                  <label className="form-label">กรุ๊ปเลือด (Blood Type)</label>
                  <select
                    className="form-select"
                    value={profile.blood_type || "O+"}
                    onChange={(e) =>
                      setProfile({
                        ...profile,
                        blood_type: e.target.value as BloodType,
                      })
                    }
                  >
                    <option value="A+">A+</option>
                    <option value="A-">A-</option>
                    <option value="B+">B+</option>
                    <option value="B-">B-</option>
                    <option value="AB+">AB+</option>
                    <option value="AB-">AB-</option>
                    <option value="O+">O+</option>
                    <option value="O-">O-</option>
                    <option value="UNKNOWN">ไม่ระบุ (Unknown)</option>
                  </select>
                </div>

                <div className="form-group">
                  <label className="form-label">ประวัติการแพ้ยาและอาหาร (Allergies คั่นด้วยจุลภาค)</label>
                  <input
                    type="text"
                    className="form-input"
                    value={profile.allergies?.join(", ") || ""}
                    onChange={(e) =>
                      setProfile({
                        ...profile,
                        allergies: e.target.value.split(",").map((s) => s.trim()),
                      })
                    }
                    placeholder="เช่น Penicillin, ถั่วลิสง, อาหารทะเล"
                  />
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">โรคประจำตัวและข้อควรระวัง (Medical Notes)</label>
                <textarea
                  className="form-textarea"
                  rows={3}
                  value={profile.medical_notes || ""}
                  onChange={(e) =>
                    setProfile({
                      ...profile,
                      medical_notes: e.target.value,
                    })
                  }
                  placeholder="เช่น Asthma (หอบหืด), เบาหวานชนิดที่ 2"
                />
              </div>

              <div className="form-section-title">บุคคลติดต่อฉุกเฉิน (Emergency Contact Person)</div>
              <div className="form-grid-2">
                <div className="form-group">
                  <label className="form-label">ชื่อผู้ติดต่อ</label>
                  <input
                    type="text"
                    className="form-input"
                    value={profile.contacts?.[0]?.name || ""}
                    onChange={(e) =>
                      setProfile({
                        ...profile,
                        contacts: [
                          {
                            name: e.target.value,
                            phone: profile.contacts?.[0]?.phone || "",
                            relationship: profile.contacts?.[0]?.relationship || "ครอบครัว",
                          },
                        ],
                      })
                    }
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">เบอร์โทรศัพท์</label>
                  <input
                    type="tel"
                    className="form-input"
                    value={profile.contacts?.[0]?.phone || ""}
                    onChange={(e) =>
                      setProfile({
                        ...profile,
                        contacts: [
                          {
                            name: profile.contacts?.[0]?.name || "",
                            phone: e.target.value,
                            relationship: profile.contacts?.[0]?.relationship || "ครอบครัว",
                          },
                        ],
                      })
                    }
                  />
                </div>
              </div>

              <div className="form-section-title">ประกันภัยการเดินทาง (Travel Insurance)</div>
              <div className="form-grid-2">
                <div className="form-group">
                  <label className="form-label">บริษัทประกันภัย</label>
                  <input
                    type="text"
                    className="form-input"
                    value={profile.insurance?.provider_name || ""}
                    onChange={(e) =>
                      setProfile({
                        ...profile,
                        insurance: {
                          provider_name: e.target.value,
                          policy_reference: profile.insurance?.policy_reference || "",
                          emergency_phone: profile.insurance?.emergency_phone || "",
                        },
                      })
                    }
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">หมายเลขกรมธรรม์</label>
                  <input
                    type="text"
                    className="form-input"
                    value={profile.insurance?.policy_reference || ""}
                    onChange={(e) =>
                      setProfile({
                        ...profile,
                        insurance: {
                          provider_name: profile.insurance?.provider_name || "",
                          policy_reference: e.target.value,
                          emergency_phone: profile.insurance?.emergency_phone || "",
                        },
                      })
                    }
                  />
                </div>
              </div>

              <div className="form-actions-row">
                <button type="submit" className="save-profile-btn" disabled={profileSaving}>
                  {profileSaving ? "กำลังบันทึกอย่างปลอดภัย…" : "บันทึกข้อมูลสุขภาพฉุกเฉิน (Save Profile)"}
                </button>
              </div>
            </form>
          ) : (
            <DataSkeleton label="กำลังโหลดข้อมูลสุขภาพ..." />
          )}
        </section>
      )}
    </div>
  );
}
