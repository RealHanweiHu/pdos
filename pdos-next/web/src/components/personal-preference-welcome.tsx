"use client";

import { useEffect, useState } from "react";
import { ArrowUpRight, Sparkle } from "@phosphor-icons/react";
import type { browserApi } from "@/lib/browser-api";
import type { PreferenceView } from "@/lib/personal-preferences";
import { PaiWelcome } from "./pai-conversation";
import styles from "./pai-conversation.module.css";
import preferencesStyles from "./personal-preferences.module.css";

/** Suggestions only fill the composer; current chat scope is never changed. */
export function PersonalPreferenceWelcome({ api, onSuggest }: { api: typeof browserApi; onSuggest: (text: string) => void }) {
  const [reading, setReading] = useState<PreferenceView | null>(null);
  useEffect(() => {
    let active = true, sequence = 0;
    const refresh = () => {
      const request = ++sequence;
      setReading(null);
      void api<PreferenceView>("v1/personal/preferences").then(value => {
        if (active && request === sequence && Array.isArray(value?.role_defaults?.welcome_examples) && Array.isArray(value.navigation_candidates)) setReading(value);
      }).catch(() => { /* Optional personalization must not block chat. */ });
    };
    refresh();
    window.addEventListener("focus", refresh);
    return () => { active = false; window.removeEventListener("focus", refresh); };
  }, [api]);
  const examples = reading?.role_defaults.welcome_examples ?? [];
  const candidates = reading?.navigation_candidates ?? [];
  if (!examples.length && !candidates.length) return <PaiWelcome onSuggest={onSuggest}/>;
  return <div className={styles.empty}>
    <Sparkle size={25} aria-hidden="true"/><h1>有什么想一起解决的？</h1><p>从一个问题、一个想法，或一份资料开始。</p>
    <div className={styles.suggestions}>{(examples.length ? examples : ["帮我梳理一个想法", "起草一份工作方案", "比较两个方案"]).map(text => <button key={text} type="button" onClick={() => onSuggest(text)}>{text}<ArrowUpRight size={12} aria-hidden="true"/></button>)}</div>
    {!!candidates.length && <nav aria-label="常用范围候选" className={`${styles.suggestions} ${preferencesStyles.welcomeNavigation}`}>{candidates.map(item => <a key={`${item.kind}:${item.id}`} href={item.href}>{item.label}<ArrowUpRight size={12} aria-hidden="true"/></a>)}</nav>}
  </div>;
}
