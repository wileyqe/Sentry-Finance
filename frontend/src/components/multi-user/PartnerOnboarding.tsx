/**
 * PartnerOnboarding — step-by-step flow for adding a partner/co-user.
 *
 * Steps:
 * 1. Enable multi-user mode (if not already on)
 * 2. Name yourself (primary owner)
 * 3. Add partner + assign accounts
 *
 * Appears inline on the Settings page when multi-user is first toggled on.
 */

import { useState, useEffect } from "react";
import { apiFetch, useMutation } from "../../lib/api";
import { useView } from "../../context/ViewContext";
import "./PartnerOnboarding.css";

interface Account {
  id: string;
  name: string;
  type: string;
  institution_id: string;
}

// Owner unused

export default function PartnerOnboarding({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState(1);
  const [myName, setMyName] = useState("");
  const [partnerName, setPartnerName] = useState("");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [partnerAccounts, setPartnerAccounts] = useState<Set<string>>(new Set());
  const [sharedAccounts, setSharedAccounts] = useState<Set<string>>(new Set());
  // owners array removed to fix TS error
  const { refetchOwners } = useView();

  const [doPost] = useMutation("POST");
  const [doPatch] = useMutation("PATCH");

  useEffect(() => {
    apiFetch<{ accounts: Account[] }>("/api/accounts").then((res) =>
      setAccounts(res.accounts || [])
    );
    // fetch owners intentionally removed
  }, []);

  const handleSetMyName = async () => {
    if (!myName.trim()) return;
    await doPost(`/api/owners?owner_id=mine&display_name=${encodeURIComponent(myName.trim())}`);
    setStep(2);
  };

  const handleAddPartner = async () => {
    if (!partnerName.trim()) return;
    await doPost(`/api/owners?owner_id=theirs&display_name=${encodeURIComponent(partnerName.trim())}`);

    // Assign partner accounts
    for (const acctId of partnerAccounts) {
      await doPatch(`/api/accounts/${acctId}/owner?owner_id=theirs`);
    }

    // Assign shared accounts (clear owner to make them "ours")
    for (const acctId of sharedAccounts) {
      await doPatch(`/api/accounts/${acctId}/owner`);
    }

    refetchOwners();
    setStep(3);
  };

  const togglePartnerAccount = (id: string) => {
    setPartnerAccounts((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
        sharedAccounts.delete(id);
        setSharedAccounts(new Set(sharedAccounts));
      }
      return next;
    });
  };

  const toggleSharedAccount = (id: string) => {
    setSharedAccounts((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
        partnerAccounts.delete(id);
        setPartnerAccounts(new Set(partnerAccounts));
      }
      return next;
    });
  };

  if (step === 3) {
    return (
      <div className="partner-onboarding">
        <div className="partner-onboarding__complete">
          <div className="partner-onboarding__check">✓</div>
          <h3>Multi-User Setup Complete!</h3>
          <p>
            You can now use the view selector at the top of any page to switch
            between <strong>{myName}</strong>, <strong>{partnerName}</strong>,
            and <strong>Household</strong> views.
          </p>
          <button className="partner-onboarding__btn" onClick={onComplete}>
            Got it
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="partner-onboarding">
      <div className="partner-onboarding__header">
        <h3>Multi-User Setup</h3>
        <div className="partner-onboarding__steps">
          <span className={`partner-onboarding__step ${step >= 1 ? "active" : ""}`}>
            1. Your Name
          </span>
          <span className="partner-onboarding__step-sep">→</span>
          <span className={`partner-onboarding__step ${step >= 2 ? "active" : ""}`}>
            2. Add Partner
          </span>
        </div>
      </div>

      {step === 1 && (
        <div className="partner-onboarding__section">
          <label className="partner-onboarding__label">What should we call you?</label>
          <input
            className="partner-onboarding__input"
            placeholder="e.g. Chris"
            value={myName}
            onChange={(e) => setMyName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSetMyName()}
            autoFocus
          />
          <button
            className="partner-onboarding__btn"
            onClick={handleSetMyName}
            disabled={!myName.trim()}
          >
            Continue
          </button>
        </div>
      )}

      {step === 2 && (
        <div className="partner-onboarding__section">
          <label className="partner-onboarding__label">Partner's name</label>
          <input
            className="partner-onboarding__input"
            placeholder="e.g. Taylor"
            value={partnerName}
            onChange={(e) => setPartnerName(e.target.value)}
            autoFocus
          />

          <label className="partner-onboarding__label partner-onboarding__label--mt">
            Assign accounts to {partnerName || "your partner"}
          </label>
          <p className="partner-onboarding__hint">
            Unselected accounts default to <strong>{myName}</strong>. 
            Shared accounts appear in both individual views.
          </p>

          <div className="partner-onboarding__accounts">
            {accounts.map((a) => (
              <div key={a.id} className="partner-onboarding__account-row">
                <span className="partner-onboarding__account-name">
                  {a.name}
                  <span className="partner-onboarding__account-type">{a.type}</span>
                </span>
                <div className="partner-onboarding__account-actions">
                  <button
                    className={`partner-onboarding__tag ${
                      partnerAccounts.has(a.id) ? "partner-onboarding__tag--partner" : ""
                    }`}
                    onClick={() => togglePartnerAccount(a.id)}
                  >
                    {partnerName || "Partner"}
                  </button>
                  <button
                    className={`partner-onboarding__tag ${
                      sharedAccounts.has(a.id) ? "partner-onboarding__tag--shared" : ""
                    }`}
                    onClick={() => toggleSharedAccount(a.id)}
                  >
                    Shared
                  </button>
                </div>
              </div>
            ))}
          </div>

          <button
            className="partner-onboarding__btn"
            onClick={handleAddPartner}
            disabled={!partnerName.trim()}
          >
            Finish Setup
          </button>
        </div>
      )}
    </div>
  );
}
