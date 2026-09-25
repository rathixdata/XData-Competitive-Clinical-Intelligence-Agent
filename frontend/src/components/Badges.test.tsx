import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BandBadge, BasisBadge, ReviewBadge } from './Badges';
import { BANDS } from '../api/types';

describe('BandBadge', () => {
  it.each(BANDS)('shows the %s text label with its band class', (band) => {
    const { container } = render(<BandBadge band={band} />);
    expect(screen.getByText(band)).toBeInTheDocument();
    const el = container.querySelector('.band');
    expect(el?.className).toMatch(/band-(archive|feed|analyst-review|high-priority|executive-alert)/);
  });

  it('includes the rounded score when given', () => {
    render(<BandBadge band="Executive Alert" score={93.2} />);
    expect(screen.getByText('93')).toBeInTheDocument();
    expect(screen.getByTitle(/Executive alert/i)).toHaveClass('band-executive-alert');
  });

  it('falls back to a neutral style for unknown bands but still shows text', () => {
    const { container } = render(<BandBadge band="Something new" />);
    expect(screen.getByText('Something new')).toBeInTheDocument();
    expect(container.querySelector('.band-archive')).not.toBeNull();
  });
});

describe('other semantic badges', () => {
  it('distinguishes sourced vs inferred dates by text', () => {
    render(
      <>
        <BasisBadge basis="SOURCED" />
        <BasisBadge basis="INFERRED" />
      </>,
    );
    expect(screen.getByText('Sourced')).toBeInTheDocument();
    expect(screen.getByText('Inferred')).toBeInTheDocument();
  });

  it('marks human-reviewed and human-edited output', () => {
    render(<ReviewBadge status="Analyst-reviewed" humanEdited />);
    expect(screen.getByText('Analyst-reviewed')).toBeInTheDocument();
    expect(screen.getByText('Human-edited')).toBeInTheDocument();
  });

  it('marks machine output as not reviewed', () => {
    render(<ReviewBadge status="Machine" />);
    expect(screen.getByText(/not reviewed/)).toBeInTheDocument();
  });
});
