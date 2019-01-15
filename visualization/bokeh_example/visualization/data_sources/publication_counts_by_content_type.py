import logging

from data_access import data_cache

logger = logging.getLogger(__name__)


def create_dataset(query, top_matches_df, top_matches_selected_indices):
    df = top_matches_df
    indices = [top_matches_selected_indices[i] for i in
               range(min(len(top_matches_selected_indices), len(df.index)))]
    logger.info(indices)
    related_ids = df.id.iloc[indices].values
    api = data_cache.get_model_data_access_api(query.content_type)
    df = api.get_full_text_matches(query.search, facet_filters=query.filters)
    return api.get_year_related_counts(df=df, related_ids=related_ids)
