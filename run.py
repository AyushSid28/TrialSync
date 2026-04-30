if __name__ == "__main__":
    import uvicorn
    from src.core import settings

    # Note: Cannot use both reload and workers at the same time
    # reload is for development, workers is for production
    uvicorn.run(
        "src.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,  # Only use in development
        log_level=settings.LOG_LEVEL.lower(),
    )
