import { useEffect, useState } from "react";

import type { CaptchaChallenge } from "../contracts";

interface Props {
  challenge: CaptchaChallenge | null;
  submitting: boolean;
  refreshing: boolean;
  onSubmit: (value: string) => Promise<void>;
  onRefresh: () => Promise<void>;
}

export function CaptchaPanel({ challenge, submitting, refreshing, onSubmit, onRefresh }: Props) {
  const [value, setValue] = useState("");
  useEffect(() => setValue(""), [challenge?.captchaId]);
  if (!challenge) return null;

  return (
    <section className="panel captcha-panel">
      <div className="panel-heading">
        <span className="step-number">3</span>
        <div><h2>Enter CAPTCHA</h2><p>The system fills the VAHAN filters before showing the final CAPTCHA image.</p></div>
      </div>
      {challenge.invalid && <p className="error-message">Incorrect CAPTCHA. A new image was loaded from VAHAN. Please try again.</p>}
      {challenge.refreshed && <p className="captcha-refresh-message">The CAPTCHA has changed. Enter the text shown in the new image.</p>}
      <img className="captcha-image" src={challenge.imageDataUrl} alt="VAHAN CAPTCHA" />
      <button
        className="secondary-button captcha-refresh-button"
        disabled={submitting || refreshing}
        onClick={onRefresh}
      >
        {refreshing ? "LOADING NEW CAPTCHA..." : "↻ REFRESH CAPTCHA"}
      </button>
      <p className="security-note">If automatic recognition needs help, enter the full CAPTCHA manually on VAHAN. Apply runs after all 6 characters are entered.</p>
    </section>
  );
}
