import { useLang, useT } from '../../lib/i18n.ts';
import { useUi } from '../../store/ui.ts';
import { BarChart } from 'echarts/charts';
import {
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { useEffect, useRef } from 'react';
import { formatCount, monthLong } from '../../lib/format.ts';
import { registerChart } from './chartHandle.ts';
import type { CalendarModel } from './model.ts';

echarts.use([
  BarChart,
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
]);

const token = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** Serie del mes seleccionado en todos los años, con la mediana y la banda P25–P75. */
export default function MonthChart({ model }: { model: CalendarModel }) {
  const t = useT();
  const lang = useLang((s) => s.lang);
  // Los colores salen de los tokens CSS: hay que repintar al cambiar de tema o de daltonismo
  const theme = useUi((s) => s.theme);
  const cvd = useUi((s) => s.cvd);
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts>(null);

  useEffect(() => {
    if (!el.current) return;
    const instance = echarts.init(el.current);
    chart.current = instance;
    registerChart(() =>
      instance.getDataURL({
        type: 'png',
        pixelRatio: 2,
        backgroundColor: token('--color-surface'),
      }),
    );
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(el.current);
    return () => {
      observer.disconnect();
      registerChart(undefined);
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    // Un fotograma después: el shell aplica el tema al documento en su propio efecto, que corre
    // después de este
    const frame = requestAnimationFrame(() => paint());
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, lang, theme, cvd]);

  function paint() {
    const ink = token('--color-ink');
    const muted = token('--color-ink-muted');
    const line = token('--color-line');
    const { reference: ref, selectedMonth, series, values, infos, years } = model;
    const hasRef = Number.isFinite(ref.median);

    const data = years
      .map((year) => ({ year, mi: (year - series.startYear) * 12 + selectedMonth }))
      .filter(({ mi }) => infos[mi].state !== 'sin datos')
      .map(({ year, mi }) => {
        const active = mi === model.selected;
        const partial = infos[mi].state === 'parcial';
        return {
          name: String(year),
          value: Number(values[mi].toFixed(2)),
          itemStyle: {
            color: active ? token('--color-accent') : token('--color-line-strong'),
            // Mes incompleto: barra hueca con borde discontinuo, no solo otro color
            ...(partial && {
              color: 'transparent',
              borderColor: active ? token('--color-accent') : muted,
              borderWidth: 1.5,
              borderType: 'dashed' as const,
            }),
          },
          label: {
            show: active,
            position: 'top' as const,
            color: ink,
            formatter: () => formatCount(values[mi]),
          },
        };
      });

    chart.current?.setOption(
      {
        animationDuration: 160,
        textStyle: { fontFamily: token('--font-sans') },
        grid: { left: 8, right: 64, top: 24, bottom: 4, containLabel: true },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          backgroundColor: token('--color-raised'),
          borderColor: token('--color-line-strong'),
          textStyle: { color: ink },
          valueFormatter: (v: unknown) => formatCount(Number(v)),
        },
        xAxis: {
          type: 'category',
          data: data.map((d) => d.name),
          axisLabel: { color: muted, fontSize: 12, formatter: (y: string) => `'${y.slice(2)}` },
          axisLine: { lineStyle: { color: line } },
          axisTick: { show: false },
        },
        yAxis: {
          type: 'value',
          axisLabel: { color: muted, fontSize: 12, formatter: (v: number) => formatCount(v) },
          splitLine: { lineStyle: { color: line } },
        },
        series: [
          {
            type: 'bar',
            name: monthLong(selectedMonth),
            data,
            barMaxWidth: 22,
            markLine: hasRef
              ? {
                  silent: true,
                  symbol: 'none',
                  lineStyle: { color: ink, type: 'dashed', width: 1.5 },
                  label: { color: ink, formatter: t('Mediana'), position: 'end' },
                  data: [{ yAxis: Number(ref.median.toFixed(2)) }],
                }
              : undefined,
            markArea: hasRef
              ? {
                  silent: true,
                  itemStyle: { color: ink, opacity: 0.1 },
                  data: [[{ yAxis: ref.p25 }, { yAxis: ref.p75 }]],
                }
              : undefined,
          },
        ],
      },
      true,
    );
  }

  return (
    <div
      ref={el}
      role="img"
      aria-label={t(
        'Detecciones de {mes} en cada año, con la mediana y la banda entre los percentiles 25 y 75',
        { mes: monthLong(model.selectedMonth) },
      )}
      className="h-44 w-full"
    />
  );
}
