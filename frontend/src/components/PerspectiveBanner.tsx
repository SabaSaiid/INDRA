'use client';

/**
 * INDRA Platform — Admin Perspective Banner
 *
 * Rendered at the very top of the viewport whenever an Admin is simulating
 * another role. Always visible, always one-click escapable, so the operator
 * is never confused about which persona they are viewing through.
 */

import React from 'react';
import { Eye, RotateCcw, ChevronDown } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useRoleContext, ROLE_PERSPECTIVES, type EffectiveRole } from '@/lib/useRoleContext';

export default function PerspectiveBanner() {
  const { effectiveRole, isImpersonating, resetPerspective, setPerspective } = useRoleContext();
  const [pickerOpen, setPickerOpen] = React.useState(false);

  if (!isImpersonating || !effectiveRole) return null;

  const perspective = ROLE_PERSPECTIVES.find((p) => p.role === effectiveRole);
  if (!perspective) return null;

  return (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: 'auto', opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
      className="relative z-[60] w-full border-b"
      style={{
        background: `linear-gradient(135deg, ${perspective.color}18 0%, ${perspective.color}08 100%)`,
        borderColor: `${perspective.color}30`,
      }}
    >
      <div className="flex items-center justify-between px-4 py-2 max-w-[1800px] mx-auto gap-3">
        {/* Left: perspective label */}
        <div className="flex items-center gap-2.5 min-w-0">
          <div
            className="flex items-center justify-center w-6 h-6 rounded-md flex-shrink-0"
            style={{ background: `${perspective.color}20` }}
          >
            <Eye className="w-3.5 h-3.5" style={{ color: perspective.color }} />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className="text-xs font-bold tracking-wide uppercase"
                style={{ color: perspective.color }}
              >
                Viewing as: {perspective.label}
              </span>
              <span
                className="text-[10px] font-medium px-1.5 py-0.5 rounded border"
                style={{
                  color: perspective.color,
                  borderColor: `${perspective.color}30`,
                  background: `${perspective.color}10`,
                }}
              >
                Simulated Viewport
              </span>
            </div>
            <p className="text-[10px] text-[#7A8599] mt-0.5 truncate">
              {perspective.description}
            </p>
          </div>
        </div>

        {/* Right: actions */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {/* Quick switch */}
          <div className="relative">
            <button
              onClick={() => setPickerOpen(!pickerOpen)}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold transition-all border hover:shadow-sm"
              style={{
                color: '#4A5568',
                borderColor: '#E8E2D4',
                background: '#FDFAF5',
              }}
            >
              Switch
              <ChevronDown className={`w-3 h-3 transition-transform ${pickerOpen ? 'rotate-180' : ''}`} />
            </button>

            <AnimatePresence>
              {pickerOpen && (
                <motion.div
                  initial={{ opacity: 0, y: 4, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 4, scale: 0.95 }}
                  transition={{ duration: 0.12 }}
                  className="absolute right-0 mt-1 w-56 rounded-xl border border-[#E8E2D4] shadow-lg z-[70] overflow-hidden"
                  style={{ background: '#FDFAF5' }}
                >
                  {ROLE_PERSPECTIVES.map((p) => (
                    <button
                      key={p.role}
                      onClick={() => {
                        setPerspective(p.role);
                        setPickerOpen(false);
                      }}
                      className={`w-full flex items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-[#F0EBE0] ${
                        effectiveRole === p.role ? 'bg-[#F0EBE0]' : ''
                      }`}
                    >
                      <span
                        className="w-2 h-2 rounded-full flex-shrink-0"
                        style={{ background: p.color }}
                      />
                      <div className="min-w-0">
                        <span className="text-[11px] font-semibold text-[#1B2432] block truncate">
                          {p.label}
                        </span>
                        <span className="text-[9px] text-[#7A8599] block truncate">
                          {p.description}
                        </span>
                      </div>
                      {effectiveRole === p.role && (
                        <span className="ml-auto text-[9px] font-bold uppercase" style={{ color: p.color }}>
                          Active
                        </span>
                      )}
                    </button>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Return to Admin */}
          <button
            onClick={resetPerspective}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold transition-all text-white shadow-sm hover:shadow-md hover:brightness-110 active:scale-95"
            style={{ background: '#7C3AED' }}
          >
            <RotateCcw className="w-3 h-3" />
            Return to Admin View
          </button>
        </div>
      </div>
    </motion.div>
  );
}
