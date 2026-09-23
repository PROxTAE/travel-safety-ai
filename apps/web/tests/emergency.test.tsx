import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EmergencyView } from "@/features/emergency/emergency-view";
import { api } from "@/lib/api/client";

describe("EmergencyView", () => {
  const mockDirectory = [
    {
      contact_id: "c-1",
      country_code: "TH",
      service_type: "POLICE",
      label: "Tourist Police Hotline",
      authority: "Royal Thai Police",
      phone: "1155",
      notes: "English-speaking operators available 24/7",
    },
    {
      contact_id: "c-2",
      country_code: "TH",
      service_type: "AMBULANCE",
      label: "National Emergency Medical Service",
      authority: "Ministry of Public Health",
      phone: "1669",
      notes: "Nationwide ambulance dispatch",
    },
  ];

  const mockProfile = {
    profile_id: "ep-1",
    user_id: "u-1",
    blood_type: "O+",
    allergies: ["Penicillin"],
    medical_notes: "Asthma",
    insurance: {
      provider_name: "Allianz Global",
      policy_reference: "POL-99231",
      emergency_phone: "+6621234567",
    },
    contacts: [
      {
        name: "Bob Doe",
        relationship: "Spouse",
        phone: "+66812345678",
        priority: 1,
      },
    ],
  };

  it("renders SOS button, official directory, and emergency profile tabs", async () => {
    vi.spyOn(api, "GET").mockImplementation(async (path) => {
      if (path === "/api/v1/emergency/contacts") {
        return { data: { data: mockDirectory } } as never;
      }
      if (path === "/api/v1/me/emergency-profile") {
        return { data: { data: mockProfile } } as never;
      }
      return { data: null } as never;
    });

    render(<EmergencyView />);

    expect(screen.getByText("HOLD SOS")).toBeInTheDocument();

    // Switch to Verified Directory tab
    const dirTab = screen.getByText(/Verified Directory/i);
    fireEvent.click(dirTab);

    await waitFor(() => {
      expect(screen.getByText("Tourist Police Hotline")).toBeInTheDocument();
      expect(screen.getByText("1155")).toBeInTheDocument();
      expect(screen.getByText("National Emergency Medical Service")).toBeInTheDocument();
      expect(screen.getByText("1669")).toBeInTheDocument();
    });

    // Switch to Medical Profile tab
    const profileTab = screen.getByText(/Medical Profile/i);
    fireEvent.click(profileTab);

    await waitFor(() => {
      expect(screen.getByDisplayValue("O+")).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue("Penicillin")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Asthma")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Bob Doe")).toBeInTheDocument();
  });
});
