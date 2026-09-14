'use client';

import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { fadeSlideUp } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import { eventDistribution, type DistributionItem } from '@/lib/mock-data';
import { fetchEventDistribution } from '@/lib/api';
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
} from 'recharts';

export default function EventDistributionChart() {
  const [animate, setAnimate] = useState(false);
  const [distribution, setDistribution] = useState<DistributionItem[]>(eventDistribution);

  useEffect(() => {
    const timer = setTimeout(() => setAnimate(true), 300);
    return () => clearTimeout(timer);
  }, []);

  // Fetch live distribution data
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchEventDistribution();
        if (!cancelled && data.length > 0) {
          setDistribution(data);
        }
      } catch {
        // mock data already set
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const total = distribution.reduce((sum, item) => sum + item.value, 0);

  return (
    <motion.div
      variants={fadeSlideUp}
      initial="hidden"
      animate="visible"
      transition={{ delay: 0.5 }}
    >
      <Card hover={false} className="h-full">
        <CardHeader title="Event Distribution" />

        <div className="flex items-center gap-4">
          {/* Donut chart */}
          <div className="relative w-[160px] h-[160px] flex-shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={distribution}
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={72}
                  paddingAngle={2}
                  dataKey="value"
                  startAngle={90}
                  endAngle={animate ? -270 : 90}
                  animationBegin={0}
                  animationDuration={1200}
                  animationEasing="ease-out"
                  stroke="white"
                  strokeWidth={2}
                >
                  {distribution.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>

            {/* Center total */}
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <motion.span
                initial={{ opacity: 0, scale: 0.5 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 0.8, duration: 0.4, ease: 'easeOut' }}
                className="text-2xl font-bold text-text-primary tabular-nums"
              >
                {total}
              </motion.span>
              <span className="text-[10px] text-text-muted">Events</span>
            </div>
          </div>

          {/* Legend */}
          <div className="flex-1 space-y-2">
            {distribution.map((item, index) => (
              <motion.div
                key={item.name}
                initial={{ opacity: 0, x: 10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.5 + index * 0.06, duration: 0.3 }}
                className="flex items-center justify-between"
              >
                <div className="flex items-center gap-2">
                  <div
                    className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{ backgroundColor: item.color }}
                  />
                  <span className="text-xs text-text-secondary">{item.name}</span>
                </div>
                <span className="text-xs font-semibold text-text-primary tabular-nums">
                  {item.value}
                </span>
              </motion.div>
            ))}
          </div>
        </div>
      </Card>
    </motion.div>
  );
}
