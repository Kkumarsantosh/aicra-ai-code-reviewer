import React from 'react';

/**
 * RevealCard component provides a "reveal" animation effect on hover.
 * It uses a clip-path circle that expands from a specific origin.
 * 
 * Logic converted from GSAP to pure CSS for maximum performance and portability.
 */

interface RevealCardProps {
  base: React.ReactNode;
  overlay: React.ReactNode;
  accentColor?: string;
  originX?: string; // e.g. "56px"
  originY?: string; // e.g. "56px"
  className?: string;
}

export const RevealCard: React.FC<RevealCardProps> = ({
  base,
  overlay,
  accentColor = 'var(--accent-primary)',
  originX = '56px',
  originY = '56px',
  className = '',
}) => {
  const containerStyle = {
    '--accent-color': accentColor,
    '--origin-x': originX,
    '--origin-y': originY,
  } as React.CSSProperties;

  return (
    <div className={`reveal-card-container ${className}`} style={containerStyle}>
      {/* The Base Card Content */}
      <div className="reveal-card-base">
        {base}
      </div>

      {/* The Animated Overlay Card (Revealed on Hover) */}
      <div 
        className="reveal-card-overlay"
        style={{
          clipPath: `circle(0px at ${originX} ${originY})`,
        }}
      >
        {overlay}
      </div>

      <style jsx>{`
        .reveal-card-container {
          position: relative;
          overflow: hidden;
          border-radius: 2rem;
          cursor: pointer;
          background: #ffffff;
          border: 1px solid var(--border);
          transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .reveal-card-container:hover {
          transform: translateY(-8px) scale(1.01);
          box-shadow: 0 20px 40px rgba(0,0,0,0.05);
          border-color: var(--accent-color);
        }

        .reveal-card-base {
          position: relative;
          z-index: 1;
          width: 100%;
          height: 100%;
        }

        .reveal-card-overlay {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          z-index: 2;
          background: var(--accent-color);
          color: #ffffff;
          pointer-events: none;
          transition: clip-path 0.8s cubic-bezier(0.19, 1, 0.22, 1);
        }

        .reveal-card-container:hover .reveal-card-overlay {
          clip-path: circle(160% at var(--origin-x) var(--origin-y)) !important;
          pointer-events: auto;
        }
      `}</style>
    </div>
  );
};
