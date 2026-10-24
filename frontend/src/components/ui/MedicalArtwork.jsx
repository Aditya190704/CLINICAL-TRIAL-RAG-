import React from "react";

/** Decorative clinical illustration used to give the app a calm medical identity. */
export default function MedicalArtwork({ className = "" }) {
  return (
    <svg className={className} viewBox="0 0 460 300" fill="none" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="medical-panel" x1="48" y1="28" x2="392" y2="274" gradientUnits="userSpaceOnUse">
          <stop stopColor="#fff" />
          <stop offset="1" stopColor="#dceeff" />
        </linearGradient>
        <linearGradient id="medical-cross" x1="275" y1="69" x2="336" y2="137" gradientUnits="userSpaceOnUse">
          <stop stopColor="#79b6ee" />
          <stop offset="1" stopColor="#4387d0" />
        </linearGradient>
      </defs>
      <circle cx="231" cy="150" r="126" fill="url(#medical-panel)" />
      <circle cx="231" cy="150" r="102" stroke="#c6def4" strokeDasharray="3 8" />
      <path d="M102 153h51l18-35 27 70 24-48 17 25h118" stroke="#66a5df" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M265 82h42v18h18v42h-18v18h-42v-18h-18v-42h18V82Z" fill="url(#medical-cross)" stroke="white" strokeWidth="5" strokeLinejoin="round" />
      <path d="M286 94v54M259 121h54" stroke="white" strokeWidth="8" strokeLinecap="round" />
      <circle cx="126" cy="92" r="19" fill="#eff7ff" stroke="#c5def4" strokeWidth="2" />
      <path d="M126 82v20M116 92h20" stroke="#609dd4" strokeWidth="3" strokeLinecap="round" />
      <circle cx="365" cy="193" r="15" fill="#eff7ff" stroke="#c5def4" strokeWidth="2" />
      <path d="M365 185v16M357 193h16" stroke="#609dd4" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="174" cy="228" r="5" fill="#70ace0" />
      <circle cx="204" cy="241" r="4" fill="#9dc7ea" />
      <path d="M177 229c15 2 19 5 26 11" stroke="#9dc7ea" strokeWidth="2" strokeDasharray="3 5" />
      <path d="M79 201c12-9 20-8 29 0s17 9 29 0" stroke="#9fc7e9" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
