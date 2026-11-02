import { describe, it, expect } from 'vitest';
import { benchmarkKey, canonicalCharacterName } from './characters';

describe('canonicalCharacterName', () => {
  it('国別表記を英語名に寄せる', () => {
    expect(canonicalCharacterName('GOUKI')).toBe('AKUMA');
    expect(canonicalCharacterName('AKUMA')).toBe('AKUMA');
    expect(canonicalCharacterName('VEGA')).toBe('MBISON');
    expect(canonicalCharacterName('M. BISON')).toBe('MBISON');
  });

  it('記号と空白を除去する', () => {
    expect(canonicalCharacterName('A.K.I.')).toBe('AKI');
    expect(canonicalCharacterName('E.HONDA')).toBe('EHONDA');
    expect(canonicalCharacterName('DEE JAY')).toBe('DEEJAY');
    expect(canonicalCharacterName('CHUN-LI')).toBe('CHUNLI');
  });

  it('前後の空白と小文字を吸収する', () => {
    expect(canonicalCharacterName('  luke  ')).toBe('LUKE');
  });

  it('Battlelog の日本語名を英語名に寄せる', () => {
    expect(canonicalCharacterName('ルーク')).toBe('LUKE');
    expect(canonicalCharacterName('豪鬼')).toBe('AKUMA');
    expect(canonicalCharacterName('ベガ')).toBe('MBISON');
    expect(canonicalCharacterName('C.ヴァイパー')).toBe('CVIPER');
    expect(canonicalCharacterName('舞')).toBe('MAI');
    expect(canonicalCharacterName('エドモンド本田')).toBe('EHONDA');
    expect(canonicalCharacterName('エド')).toBe('ED');
    expect(canonicalCharacterName('春麗')).toBe('CHUNLI');
    expect(canonicalCharacterName('アルジュン')).toBe('ARJUN');
  });
});

describe('benchmarkKey', () => {
  it('自キャラ・相手キャラ・入力タイプでキーを作る', () => {
    expect(benchmarkKey('LUKE', 'AKUMA', 'Classic')).toBe('LUKE|AKUMA|Classic');
  });

  it('バックラー側の表記でも同じキーになる', () => {
    expect(benchmarkKey('LUKE', 'GOUKI', 'Classic')).toBe(benchmarkKey('LUKE', 'AKUMA', 'Classic'));
    expect(benchmarkKey('LUKE', 'VEGA', 'Modern')).toBe(benchmarkKey('LUKE', 'M. BISON', 'Modern'));
  });

  it('Battlelog の日本語名でも同じキーになる', () => {
    expect(benchmarkKey('ルーク', '豪鬼', 'Classic')).toBe(benchmarkKey('LUKE', 'GOUKI', 'Classic'));
  });

  it('入力タイプが違えば別キーになる', () => {
    expect(benchmarkKey('LUKE', 'AKUMA', 'Classic')).not.toBe(benchmarkKey('LUKE', 'AKUMA', 'Modern'));
  });
});
