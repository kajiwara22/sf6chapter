import { describe, it, expect } from 'vitest';
import { convertJstDateToUtc, convertJstDateTimeToTimestamp } from './search';

describe('convertJstDateToUtc', () => {
  describe('isEndOfDay=false（開始日: JST 00:00:00 → UTC 前日 15:00:00）', () => {
    it('通常日付の変換', () => {
      expect(convertJstDateToUtc('2026-01-14', false)).toBe('2026-01-13T15:00:00Z');
    });

    it('月初（前日が前月末）の変換', () => {
      expect(convertJstDateToUtc('2026-02-01', false)).toBe('2026-01-31T15:00:00Z');
    });

    it('年初（前日が前年末）の変換', () => {
      expect(convertJstDateToUtc('2026-01-01', false)).toBe('2025-12-31T15:00:00Z');
    });

    it('うるう年2月29日の変換', () => {
      expect(convertJstDateToUtc('2024-03-01', false)).toBe('2024-02-29T15:00:00Z');
    });
  });

  describe('isEndOfDay=true（終了日: JST 23:59:59 → UTC 当日 14:59:59）', () => {
    it('通常日付の変換', () => {
      expect(convertJstDateToUtc('2026-01-14', true)).toBe('2026-01-14T14:59:59Z');
    });

    it('月末の変換', () => {
      expect(convertJstDateToUtc('2026-01-31', true)).toBe('2026-01-31T14:59:59Z');
    });

    it('年末の変換', () => {
      expect(convertJstDateToUtc('2025-12-31', true)).toBe('2025-12-31T14:59:59Z');
    });

    it('ゼロパディングが正しく行われる（1桁月・日）', () => {
      expect(convertJstDateToUtc('2026-03-05', true)).toBe('2026-03-05T14:59:59Z');
    });
  });
});

describe('convertJstDateTimeToTimestamp', () => {
  describe('時刻なし（isEndOfDay=false）: JST 00:00:00 → UTC 前日 15:00:00', () => {
    it('通常日付の変換', () => {
      expect(convertJstDateTimeToTimestamp('2026-01-14', false)).toBe('2026-01-13 15:00:00');
    });

    it('月初（前月末）の変換', () => {
      expect(convertJstDateTimeToTimestamp('2026-02-01', false)).toBe('2026-01-31 15:00:00');
    });

    it('年初（前年末）の変換', () => {
      expect(convertJstDateTimeToTimestamp('2026-01-01', false)).toBe('2025-12-31 15:00:00');
    });
  });

  describe('時刻なし（isEndOfDay=true）: JST 23:59:59 → UTC 当日 14:59:59', () => {
    it('通常日付の変換', () => {
      expect(convertJstDateTimeToTimestamp('2026-01-14', true)).toBe('2026-01-14 14:59:59');
    });

    it('月末の変換', () => {
      expect(convertJstDateTimeToTimestamp('2026-01-31', true)).toBe('2026-01-31 14:59:59');
    });
  });

  describe('時刻あり（isEndOfDay=false）: JST HH:MM:00 → UTC -9h', () => {
    it('日中の時刻（日付変化なし）', () => {
      // JST 14:30:00 → UTC 05:30:00
      expect(convertJstDateTimeToTimestamp('2026-01-14', false, '14:30')).toBe('2026-01-14 05:30:00');
    });

    it('9時以前（日付が前日にまたがる）', () => {
      // JST 08:00:00 → UTC 前日 23:00:00
      expect(convertJstDateTimeToTimestamp('2026-01-14', false, '08:00')).toBe('2026-01-13 23:00:00');
    });

    it('0時ちょうど（前日UTC15時）', () => {
      // JST 00:00:00 → UTC 前日 15:00:00
      expect(convertJstDateTimeToTimestamp('2026-01-14', false, '00:00')).toBe('2026-01-13 15:00:00');
    });
  });

  describe('時刻あり（isEndOfDay=true）: JST HH:MM:59 → UTC -9h', () => {
    it('日中の時刻（secondsが59になる）', () => {
      // JST 14:30:59 → UTC 05:30:59
      expect(convertJstDateTimeToTimestamp('2026-01-14', true, '14:30')).toBe('2026-01-14 05:30:59');
    });

    it('9時以前（日付が前日にまたがる）', () => {
      // JST 08:00:59 → UTC 前日 23:00:59
      expect(convertJstDateTimeToTimestamp('2026-01-14', true, '08:00')).toBe('2026-01-13 23:00:59');
    });
  });
});
