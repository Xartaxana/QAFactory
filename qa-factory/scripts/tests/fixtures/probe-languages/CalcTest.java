package com.acme;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class CalcTest {
    @Test
    void adds() {
        assertEquals(4, Calc.add(2, 2));
    }

    @Test
    void assertjAdds() {
        assertThat(Calc.add(2, 2)).as("sum").isEqualTo(4);
    }
}
