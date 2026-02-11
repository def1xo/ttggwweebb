import React from "react";

type Props = {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
  fixedTop?: boolean;
};

const StickySearch: React.FC<Props> = ({ value, onChange, placeholder = "Поиск…", hint, fixedTop = false }) => {
  return (
    <div className={`sticky-search${fixedTop ? " sticky-search--fixed-top" : ""}`} role="search" aria-label="Поиск">
      <div className="searchbar">
        <svg
          className="icon"
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden="true"
        >
          <path
            d="M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z"
            stroke="currentColor"
            strokeWidth="2"
          />
          <path
            d="M16.2 16.2 21 21"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </svg>

        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
        />

        {value ? (
          <button className="clear-btn" onClick={() => onChange("")} type="button">
            ✕
          </button>
        ) : null}
      </div>
      {hint ? <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>{hint}</div> : null}
    </div>
  );
};

export default StickySearch;
