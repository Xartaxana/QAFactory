const loadCart = async () => {
  try {
    setLoading(true)
    const response = await fetch('/api/cart')
    const items = await response.json()
    const withBooks = await Promise.all(
      items.map(async (item) => {
        const bookRes = await fetch(`/api/books/${item.bookId}`)
        const book = await bookRes.json()
        return { ...item, book }
      })
    )
    setItems(withBooks)
  } catch (error) {
    showToast('Failed to load cart', 'error')
  }
}
const update = async (itemId, quantity) => {
  const response = await fetch(`/api/cart/${itemId}`, {
    method: 'PUT',
    body: JSON.stringify({ quantity }),
  })
  if (response.ok) { loadCart() }
}
const remove = async (itemId) => {
  const response = await fetch(`/api/cart/${itemId}`, { method: 'DELETE' })
  if (!response.ok) showToast('Failed', 'error')
}
