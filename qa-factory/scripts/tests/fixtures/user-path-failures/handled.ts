export async function addToCart(id: string) {
  try {
    const response = await fetch(`/api/cart/${id}`, { method: "POST" });
    if (!response.ok) {
      throw new Error("add to cart failed");
    }
    return await response.json();
  } catch (error) {
    console.error(error);
    toast.error("Could not add the book to the cart");
  }
}
