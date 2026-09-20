"use client";

import { useState } from "react";
import { IS_DEV } from "@/lib/config";
import { getAppearance, setAppearance, type Appearance } from "@/lib/theme";

export function SettingsScreen() {
  const [language, setLanguage] = useState("en");
  const [aspect, setAspect] = useState("9:16");
  const [quality, setQuality] = useState("balanced");
  const [appearance, setAppearanceState] = useState<Appearance>(getAppearance);
  const [saved, setSaved] = useState(false);

  return (
    <>
      <h1>Settings</h1>
      <div className="field">
        <label>Appearance</label>
        <div className="chip-row">
          {(["dark", "light", "system"] as Appearance[]).map((id) => (
            <button
              key={id}
              className={`chip ${appearance === id ? "on" : ""}`}
              data-testid={`appearance-${id}`}
              onClick={() => {
                setAppearance(id);
                setAppearanceState(id);
              }}
            >
              {id[0].toUpperCase() + id.slice(1)}
            </button>
          ))}
        </div>
      </div>
      <div className="field">
        <label htmlFor="language">Language</label>
        <select id="language" value={language} onChange={(e) => setLanguage(e.target.value)}>
          <option value="en">English</option>
          <option value="tr">Turkish</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="aspect">Default aspect ratio</label>
        <select id="aspect" value={aspect} onChange={(e) => setAspect(e.target.value)}>
          <option>9:16</option>
          <option>16:9</option>
          <option>1:1</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="quality">Default quality</label>
        <select id="quality" value={quality} onChange={(e) => setQuality(e.target.value)}>
          <option value="economy">Economy</option>
          <option value="balanced">Balanced</option>
          <option value="premium">Premium</option>
        </select>
      </div>
      <p className="lede">Advanced model defaults stay Auto unless you change them in a project.</p>
      <button className="btn primary" onClick={() => setSaved(true)}>
        Save
      </button>
      {saved ? <p className="ok">Saved</p> : null}
      {IS_DEV ? (
        <div className="card" style={{ marginTop: 16 }}>
          <strong>Development</strong>
          <p className="lede">Simulated Stars. Mock worker. No paid providers.</p>
        </div>
      ) : null}
    </>
  );
}
