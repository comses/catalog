jQuery.validator.setDefaults({
    highlight: function (element, errorClass, validClass) {
        if (element.type === "radio") {
            this.findByName(element.name).addClass(errorClass).removeClass(validClass);
        } else {
            $(element).closest('.form-group').removeClass('has-success has-feedback').addClass('has-error has-feedback');
            $(element).closest('.form-group').find('i.fa').remove();
            $(element).closest('.form-group').append('<i class="fa fa-exclamation fa-lg form-control-feedback"></i>');
        }
    },
    unhighlight: function (element, errorClass, validClass) {
        if (element.type === "radio") {
            this.findByName(element.name).removeClass(errorClass).addClass(validClass);
        } else {
            $(element).closest('.form-group').removeClass('has-error has-feedback').addClass('has-success has-feedback');
            $(element).closest('.form-group').find('i.fa').remove();
            $(element).closest('.form-group').append('<i class="fa fa-check fa-lg form-control-feedback"></i>');
        }
    }
});

$.urls = {};
$.urls.SEARCH_GOOGLE_SCHOLAR = 'https://scholar.google.com/scholar?as_q=';
$.urls.DOI_ORG = 'https://doi.org/';
