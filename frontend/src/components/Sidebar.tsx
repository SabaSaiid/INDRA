'use client';

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { usePathname } from 'next/navigation';
import Link from 'next/link';
import { cn } from '@/lib/utils';
import { navItems } from '@/lib/mock-data';
import {
  CloudLightning,
  ChevronLeft,
  ChevronRight,
  X,
} from 'lucide-react';

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

export default function Sidebar({ collapsed, onToggle, mobileOpen, onMobileClose }: SidebarProps) {
  const pathname = usePathname();
  const [hoveredItem, setHoveredItem] = useState<string | null>(null);

  const activeId = navItems.find((item) => item.href === pathname)?.id ?? 'dashboard';

  const sidebarContent = (
    <div className="flex flex-col h-full">
      {/* Brand */}
      <div className={cn(
        'flex items-center gap-3 px-4 pt-5 pb-6',
        collapsed && 'justify-center px-2'
      )}>
        <div className="w-9 h-9 rounded-xl bg-primary flex items-center justify-center flex-shrink-0">
          <CloudLightning className="w-5 h-5 text-white" />
        </div>
        <AnimatePresence mode="wait">
          {!collapsed && (
            <motion.div
              initial={{ opacity: 0, width: 0 }}
              animate={{ opacity: 1, width: 'auto' }}
              exit={{ opacity: 0, width: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden whitespace-nowrap"
            >
              <h1 className="text-white font-bold text-lg leading-tight">INDRA</h1>
              <p className="text-slate-400 text-[10px] leading-tight">
                National Weather Intelligence Platform
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 space-y-1">
        {navItems.map((item) => {
          const isActive = item.id === activeId;
          const Icon = item.icon;

          return (
            <Link
              key={item.id}
              href={item.href}
              onMouseEnter={() => setHoveredItem(item.id)}
              onMouseLeave={() => setHoveredItem(null)}
              className={cn(
                'relative flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors duration-150',
                collapsed && 'justify-center px-2',
                isActive
                  ? 'text-white'
                  : 'text-slate-400 hover:text-slate-200'
              )}
              aria-current={isActive ? 'page' : undefined}
            >
              {/* Active indicator — slides between items via layoutId */}
              {isActive && (
                <motion.div
                  layoutId="sidebar-active"
                  className="absolute inset-0 bg-primary rounded-xl"
                  transition={{
                    type: 'spring',
                    stiffness: 350,
                    damping: 30,
                  }}
                />
              )}

              <span className="relative z-10 flex items-center gap-3">
                <Icon className={cn('w-5 h-5 flex-shrink-0', isActive && 'text-white')} />
                <AnimatePresence mode="wait">
                  {!collapsed && (
                    <motion.span
                      initial={{ opacity: 0, width: 0 }}
                      animate={{ opacity: 1, width: 'auto' }}
                      exit={{ opacity: 0, width: 0 }}
                      transition={{ duration: 0.15 }}
                      className="overflow-hidden whitespace-nowrap"
                    >
                      {item.label}
                    </motion.span>
                  )}
                </AnimatePresence>
              </span>

              {/* Hover glow (only when not active) */}
              {hoveredItem === item.id && !isActive && (
                <motion.div
                  layoutId="sidebar-hover"
                  className="absolute inset-0 bg-white/5 rounded-xl"
                  transition={{ duration: 0.15 }}
                />
              )}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className={cn('px-4 pb-4 mt-auto', collapsed && 'px-2')}>
        <AnimatePresence mode="wait">
          {!collapsed && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="border-t border-slate-700/50 pt-4"
            >
              <div className="flex items-start gap-2 mb-3">
                <CloudLightning className="w-4 h-4 text-slate-500 mt-0.5 flex-shrink-0" />
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  Building a Safer &amp; Weather-Ready India
                </p>
              </div>
              <p className="text-[10px] text-slate-600">v1.0.0</p>
            </motion.div>
          )}
        </AnimatePresence>
        {collapsed && (
          <div className="border-t border-slate-700/50 pt-3 text-center">
            <p className="text-[9px] text-slate-600">v1.0</p>
          </div>
        )}
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <motion.aside
        initial={false}
        animate={{ width: collapsed ? 72 : 256 }}
        transition={{ duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
        className={cn(
          'fixed left-0 top-0 h-screen z-40',
          'hidden md:flex flex-col',
          'bg-gradient-to-b from-navy-dark to-navy-light'
        )}
      >
        {/* Toggle button */}
        <button
          onClick={onToggle}
          className="absolute -right-3 top-20 z-50 w-6 h-6 rounded-full bg-white shadow-md border border-slate-200 flex items-center justify-center hover:bg-slate-50 transition-colors"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? (
            <ChevronRight className="w-3.5 h-3.5 text-slate-600" />
          ) : (
            <ChevronLeft className="w-3.5 h-3.5 text-slate-600" />
          )}
        </button>

        {sidebarContent}
      </motion.aside>

      {/* Mobile overlay */}
      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/50 z-40 md:hidden"
              onClick={onMobileClose}
            />
            <motion.aside
              initial={{ x: -280 }}
              animate={{ x: 0 }}
              exit={{ x: -280 }}
              transition={{ type: 'spring', stiffness: 300, damping: 30 }}
              className="fixed left-0 top-0 h-screen w-[280px] z-50 md:hidden bg-gradient-to-b from-navy-dark to-navy-light"
            >
              <button
                onClick={onMobileClose}
                className="absolute right-3 top-4 w-8 h-8 rounded-lg bg-white/10 flex items-center justify-center hover:bg-white/20 transition-colors"
                aria-label="Close menu"
              >
                <X className="w-4 h-4 text-white" />
              </button>
              {sidebarContent}
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
