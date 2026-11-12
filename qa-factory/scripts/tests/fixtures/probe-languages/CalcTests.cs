using Xunit;

namespace Acme.Tests
{
    public class CalcTests
    {
        // Assert.Equal(1, 1);  -- a comment: never the first assertion
        [Fact]
        public void Adds()
        {
            var note = "Assert.Equal(9, 9);";
            Assert.Equal(4, Calc.Add(2, 2));
            Assert.True(note.Length > 0);
        }

        [Fact]
        public void Throws()
        {
            Assert.Throws<System.Exception>(() => Calc.Boom());
        }

        [Fact]
        public void Concise() => Assert.Equal(1, 1);
    }
}
